"""A minimal ComfyUI API client, standard library only.

    from comfy_client import ComfyClient
    client = ComfyClient()
    client.wait_until_ready()
    name = client.upload_image("/tmp/poses/idle00.png")
    images = client.wait(client.queue(workflow))

Why hand-rolled rather than a package: this project has no third-party Python
dependencies beyond Pillow and numpy, every dependency is a thing that breaks a
build, and the four endpoints we need are small and stable. It also lets the
pipeline run under the stock system interpreter -- ComfyUI's own venv is never
touched, only spoken to over HTTP.

Three failure modes this exists to make loud:

  * **ComfyUI not running.** The stock behaviour is a connection-refused
    traceback; here it is one line saying so, and how to start it.
  * **A workflow the server rejects.** ComfyUI answers 400 with the offending
    node and the reason, which is invisible unless you read the error body.
  * **A queued prompt that never finishes.** Waiting forever on a wedged queue is
    how a build job hangs until it is killed, so every wait has a deadline.
"""

from __future__ import annotations

import json
import mimetypes
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path


class ComfyError(RuntimeError):
    """A failure that came from ComfyUI (or from it not being there)."""


class ComfyClient:
    def __init__(self, host="127.0.0.1", port=8188, client_id=None):
        self.base = f"http://{host}:{port}"
        self.client_id = client_id or uuid.uuid4().hex

    # -- transport ----------------------------------------------------------

    def _request(self, path, data=None, headers=None, method=None, timeout=30):
        request = urllib.request.Request(f"{self.base}{path}", data=data, method=method)
        for key, value in (headers or {}).items():
            request.add_header(key, value)

        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read()
        except urllib.error.HTTPError as error:
            body = error.read().decode("utf-8", errors="replace")
            raise ComfyError(f"{path} -> HTTP {error.code}: {body[:600]}") from None
        except urllib.error.URLError as error:
            raise ComfyError(
                f"cannot reach ComfyUI at {self.base} ({error.reason}).\n"
                "Start it with:  cd ~/ComfyUI && ./venv/bin/python main.py "
                "--listen 127.0.0.1") from None

    # -- endpoints ----------------------------------------------------------

    def stats(self):
        """System stats, or None when the server is not answering yet."""
        try:
            return json.loads(self._request("/system_stats", timeout=5))
        except ComfyError:
            return None

    def wait_until_ready(self, timeout=180.0, interval=2.0):
        """Block until the server answers. Loading SDXL takes a while on MPS."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.stats() is not None:
                return True
            time.sleep(interval)
        raise ComfyError(f"ComfyUI did not answer within {timeout:.0f}s at {self.base}")

    def upload_image(self, path, subfolder="", overwrite=True):
        """Upload a local image so a LoadImage node can reference it by name.

        Returns the name to put in `LoadImage.inputs.image`. The filename field
        wants a bare filename with the subfolder passed separately -- a slash in
        the name field writes a strangely-named file that LoadImage cannot find.
        """
        path = Path(path)
        boundary = f"----cerberus{uuid.uuid4().hex}"
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"

        parts = []

        def field(name, value):
            parts.append(
                f"--{boundary}\r\nContent-Disposition: form-data; "
                f"name=\"{name}\"\r\n\r\n{value}\r\n".encode("utf-8"))

        field("overwrite", "true" if overwrite else "false")
        if subfolder:
            field("subfolder", subfolder)

        parts.append(
            f"--{boundary}\r\n"
            f"Content-Disposition: form-data; name=\"image\"; "
            f"filename=\"{path.name}\"\r\nContent-Type: {content_type}\r\n\r\n"
            .encode("utf-8"))
        parts.append(path.read_bytes())
        parts.append(f"\r\n--{boundary}--\r\n".encode("utf-8"))

        body = b"".join(parts)
        raw = self._request("/upload/image", data=body, headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Content-Length": str(len(body)),
        })
        reply = json.loads(raw)
        name = reply["name"]
        return f"{reply['subfolder']}/{name}" if reply.get("subfolder") else name

    def queue(self, workflow):
        """Submit an API-format workflow. Returns the prompt id.

        A rejected workflow answers 400 with the node errors, which is the only
        useful diagnostic ComfyUI gives -- so it is surfaced, not swallowed.
        """
        body = json.dumps({"prompt": workflow, "client_id": self.client_id}).encode("utf-8")
        reply = json.loads(self._request("/prompt", data=body,
                                         headers={"Content-Type": "application/json"}))
        if reply.get("node_errors"):
            raise ComfyError(f"workflow rejected: {json.dumps(reply['node_errors'])[:800]}")
        return reply["prompt_id"]

    def history(self, prompt_id):
        raw = self._request(f"/history/{prompt_id}", timeout=15)
        return json.loads(raw).get(prompt_id)

    def wait(self, prompt_id, timeout=900.0, interval=1.5, on_tick=None):
        """Poll until the prompt finishes; returns its output image dicts.

        A deadline rather than an open-ended poll: a wedged queue should fail the
        run, not hang it until CI kills it.
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            entry = self.history(prompt_id)
            if entry:
                status = entry.get("status", {})
                if status.get("status_str") == "error":
                    raise ComfyError(f"prompt failed: {json.dumps(status)[:800]}")
                images = [image
                          for output in entry.get("outputs", {}).values()
                          for image in output.get("images", [])]
                if images:
                    return images
            if on_tick:
                on_tick()
            time.sleep(interval)
        raise ComfyError(f"prompt {prompt_id} did not finish within {timeout:.0f}s")

    def fetch(self, image):
        """Download one output image dict -> bytes."""
        query = urllib.parse.urlencode({
            "filename": image["filename"],
            "subfolder": image.get("subfolder", ""),
            "type": image.get("type", "output"),
        })
        return self._request(f"/view?{query}", timeout=60)


def main():
    """`python3 tools/ai/comfy_client.py` -- a health check, not a client demo."""
    client = ComfyClient()
    stats = client.stats()
    if stats is None:
        print(f"ComfyUI is NOT answering at {client.base}")
        return 1

    system = stats.get("system", {})
    device = (stats.get("devices") or [{}])[0]
    print(f"ComfyUI up at {client.base}")
    print(f"  comfy   {system.get('comfyui_version', '?')}")
    print(f"  python  {str(system.get('python_version', '?')).split()[0]}")
    print(f"  device  {device.get('name', '?')} ({device.get('type', '?')})")
    print(f"  vram    {device.get('vram_total', 0) / 1073741824:.1f} GB total, "
          f"{device.get('vram_free', 0) / 1073741824:.1f} GB free")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
