import asyncio
import json
import urllib.request
import urllib.error
from fastapi import WebSocket
from broker.state import logger

def fix_encoding(text: str) -> str:
    if not text:
        return text
    try:
        return text.encode('cp437').decode('utf-8')
    except (UnicodeEncodeError, UnicodeDecodeError):
        try:
            return text.encode('cp1252').decode('utf-8')
        except (UnicodeEncodeError, UnicodeDecodeError):
            return text

def trigger_langflow_sync(url: str, headers: dict, data: dict) -> tuple[bool, bool]:
    logger.info(f"Triggering Langflow API: POST {url}")
    req = urllib.request.Request(
        url,
        data=json.dumps(data).encode("utf-8"),
        headers=headers,
        method="POST"
    )
    try:
        with urllib.request.urlopen(req) as response:
            res_body = response.read().decode("utf-8")
            logger.info(f"Langflow trigger response: {res_body[:200]}")
            
            need_review = True
            if "Không phát hiện lỗi nào" in res_body or "No supported files changed" in res_body or "No reviewable files" in res_body:
                need_review = False
                
            return True, need_review
    except urllib.error.HTTPError as e:
        logger.error(f"Langflow trigger HTTP error {e.code}: {e.read().decode('utf-8', errors='ignore')}")
    except Exception as e:
        logger.error(f"Langflow trigger failed: {str(e)}")
    return False, False

async def trigger_langflow_and_notify(sessionid: str, websocket: WebSocket, url: str, headers: dict, data: dict):
    success, need_review = await asyncio.to_thread(trigger_langflow_sync, url, headers, data)
    logger.info(f"Langflow finished for session {sessionid} (success={success}, need_review={need_review}). Notifying runner to terminate.")
    try:
        await websocket.send_text(json.dumps({
            "type": "completed",
            "status": "success" if success else "error",
            "need_review": need_review,
            "message": "Langflow execution completed"
        }))
    except Exception as e:
        logger.error(f"Failed to send completed message to runner {sessionid}: {e}")
