import argparse
import asyncio
import json
import logging
import os
import platform
import ssl
import time

import cv2
from aiohttp import web
from aiortc import (
    MediaStreamTrack,
    RTCDataChannel,
    RTCPeerConnection,
    RTCSessionDescription,
    VideoStreamTrack,
)
from aiortc.contrib.media import MediaPlayer, MediaRelay
from av import VideoFrame

ROOT = os.path.dirname(__file__)


relay = None
webcam = None
new_video_track = None


async def index(request):
    content = open(os.path.join(ROOT, "index.html"), "r").read()
    return web.Response(content_type="text/html", text=content)


async def javascript(request):
    content = open(os.path.join(ROOT, "client.js"), "r").read()
    return web.Response(content_type="application/javascript", text=content)


async def offer(request):
    params = await request.json()
    offer = RTCSessionDescription(sdp=params["sdp"], type=params["type"])

    pc = RTCPeerConnection()
    pcs.add(pc)

    await server(pc, offer)

    return web.Response(
        content_type="application/json",
        text=json.dumps(
            {"sdp": pc.localDescription.sdp, "type": pc.localDescription.type}
        ),
    )


pcs = set()


async def server(pc, offer):
    @pc.on("connectionstatechange")
    async def on_connectionstatechange():
        print("Connection state is %s" % pc.connectionState)
        if pc.connectionState == "failed":
            await pc.close()
            pcs.discard(pc)

    @pc.on("track")
    def on_track(track):
        print("======= received track: ", track)
        if track.kind == "video":
            global new_video_track
            new_video_track = FaceSwapper(track)
            pc.addTrack(new_video_track)

    @pc.on("datachannel")
    def on_datachannel(channel):
        global new_video_track
        new_video_track.channel = channel
        print("mounted channel")

        @channel.on("message")
        async def on_message(message):
            if isinstance(message, str):
                data = message.encode("utf-8")
            else:
                data = message
            print("receive data: ", data)

    await pc.setRemoteDescription(offer)
    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)


async def on_shutdown(app):
    # close peer connections
    coros = [pc.close() for pc in pcs]
    await asyncio.gather(*coros)
    pcs.clear()


class FaceSwapper(VideoStreamTrack):
    kind = "video"

    def __init__(self, track):
        super().__init__()
        self.track = track
        self.channel = None

    async def recv(self):
        timestamp, video_timestamp_base = await self.next_timestamp()
        frame = await self.track.recv()
        if self.channel is not None:
            self.channel.send(
                json.dumps(
                    {
                        "now": time.time() * 1000,
                    }
                )
            )
        return frame


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="WebRTC webcam demo")
    parser.add_argument(
        "--host", default="0.0.0.0", help="Host for HTTP server (default: 0.0.0.0)"
    )
    parser.add_argument(
        "--port", type=int, default=8080, help="Port for HTTP server (default: 8080)"
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)

    app = web.Application()
    app.on_shutdown.append(on_shutdown)
    app.router.add_get("/", index)
    app.router.add_get("/client.js", javascript)
    app.router.add_post("/offer", offer)
    web.run_app(app, host=args.host, port=args.port)
