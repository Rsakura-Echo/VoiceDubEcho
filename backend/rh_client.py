"""RunningHub API 客户端 — 上传参考音频 → 提交工作流 → 轮询 → 下载 TTS 结果。"""
import json, time, random, asyncio
from pathlib import Path
from typing import Optional
import httpx

TIMEOUT = 600
POLL_INTERVAL = 3
RETRYABLE_CODES = {421, 1003, 1011, 1520}


def _host(api_url: str) -> str:
    return (api_url or "https://www.runninghub.cn").rstrip("/")


async def _upload_file(api_url: str, api_key: str, file_path: str) -> Optional[str]:
    url = f"{_host(api_url)}/task/openapi/upload"
    data = {"apiKey": api_key, "fileType": "input"}
    async with httpx.AsyncClient(timeout=120) as client:
        with open(file_path, "rb") as f:
            files = {"file": (Path(file_path).name, f)}
            resp = await client.post(url, data=data, files=files)
            resp.raise_for_status()
            result = resp.json()
    if result.get("msg") == "success":
        return result.get("data", {}).get("fileName")
    print(f"[runninghub] upload failed: {result}")
    return None


async def _submit_task(api_url: str, api_key: str, workflow_id: str, node_info_list: list) -> tuple:
    url = f"{_host(api_url)}/task/openapi/create"
    payload = {"apiKey": api_key, "workflowId": workflow_id, "nodeInfoList": node_info_list}
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(url, json=payload)
        if resp.status_code == 429:
            return None, True
        resp.raise_for_status()
        result = resp.json()
    code = result.get("code", -1)
    if code == 0:
        return result["data"]["taskId"], False
    elif code == 813:
        return result["data"]["taskId"], False
    elif code in RETRYABLE_CODES:
        print(f"[runninghub] retryable code={code}: {result.get('msg')}")
        return None, True
    elif code in (805,):
        print(f"[runninghub] permanent failure (805): {result}")
        return None, False
    else:
        print(f"[runninghub] submit failed (code={code}): {result.get('msg', result)}")
        return None, False


async def _poll_outputs(api_url: str, api_key: str, task_id: str, timeout: int) -> Optional[str]:
    url = f"{_host(api_url)}/task/openapi/outputs"
    payload = {"apiKey": api_key, "taskId": task_id}
    start = time.time()
    async with httpx.AsyncClient(timeout=30) as client:
        while time.time() - start < timeout:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            result = resp.json()
            code = result.get("code")
            data = result.get("data")
            if code == 0 and data:
                file_url = data[0].get("fileUrl") if isinstance(data, list) else data.get("fileUrl")
                if file_url:
                    return file_url
            elif code == 805:
                failed = data.get("failedReason") if data else "unknown"
                print(f"[runninghub] task failed (805): {failed}")
                return None
            elif code and code != 804 and code != 813 and code != 0:
                print(f"[runninghub] task status code={code}: {json.dumps(result, ensure_ascii=False)[:300]}")
                return None
            await asyncio.sleep(POLL_INTERVAL)
    return None


def _emo_norm(emotion_str: str, key: str) -> str:
    emotions = {}
    if emotion_str:
        try: emotions = json.loads(emotion_str)
        except: pass
    return f"{float(emotions.get(key, 0)):.2f}"


async def run_dubbing(reference_audio_path: str, text: str, project_id: str,
                      segment_id: str, segment_index: int,
                      api_url: str = "", api_key: str = "",
                      workflow_id: str = "", emotion: str = "",
                      timeout: int = TIMEOUT) -> str:
    """TTS via RunningHub — upload audio, submit, poll, download."""
    ref_filename = await _upload_file(api_url, api_key, reference_audio_path)
    if not ref_filename:
        raise RuntimeError("RunningHub上传参考音频失败")

    seed = random.randint(0, 2**31 - 1)
    node_list = [
        {"nodeId": "87",  "fieldName": "value",     "fieldValue": text},
        {"nodeId": "159", "fieldName": "audio",     "fieldValue": ref_filename},
        {"nodeId": "100", "fieldName": "Happy",     "fieldValue": _emo_norm(emotion, "happy")},
        {"nodeId": "100", "fieldName": "Angry",     "fieldValue": _emo_norm(emotion, "angry")},
        {"nodeId": "100", "fieldName": "Sad",       "fieldValue": _emo_norm(emotion, "sad")},
        {"nodeId": "100", "fieldName": "Fear",      "fieldValue": _emo_norm(emotion, "fear")},
        {"nodeId": "100", "fieldName": "Hate",      "fieldValue": _emo_norm(emotion, "hate")},
        {"nodeId": "100", "fieldName": "Low",       "fieldValue": _emo_norm(emotion, "low")},
        {"nodeId": "100", "fieldName": "Surprise",  "fieldValue": _emo_norm(emotion, "surprise")},
        {"nodeId": "100", "fieldName": "Neutral",   "fieldValue": _emo_norm(emotion, "neutral")},
        {"nodeId": "152", "fieldName": "seed",      "fieldValue": str(seed)},
    ]

    task_id = None
    while task_id is None:
        task_id, retryable = await _submit_task(api_url, api_key, workflow_id, node_list)
        if task_id is None and retryable:
            await asyncio.sleep(5)
    print(f"[runninghub] task: {task_id}")

    file_url = await _poll_outputs(api_url, api_key, task_id, timeout)
    if not file_url:
        raise RuntimeError(f"RunningHub任务超时或失败: {task_id}")

    from .config import get_project_dir
    project_dir = get_project_dir(project_id)
    dub_path = project_dir / f"dub_{segment_id[:8]}.wav"
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.get(file_url)
        resp.raise_for_status()
        dub_path.write_bytes(resp.content)
    print(f"[runninghub] done: {dub_path}")
    return str(dub_path)


async def run_clone_dubbing(voice_audio_path: str, segment_audio_path: str,
                            text: str, project_id: str, segment_id: str,
                            segment_index: int = 0,
                            api_url: str = "", api_key: str = "",
                            clone_workflow_id: str = "", emotion: str = "",
                            timeout: int = TIMEOUT) -> str:
    """Clone dub — uploads voice + segment audio, uses clone workflow nodes (5=voice, 105=seg)."""
    voice_fn = await _upload_file(api_url, api_key, voice_audio_path)
    if not voice_fn:
        raise RuntimeError("RunningHub上传音色音频失败")
    seg_fn = await _upload_file(api_url, api_key, segment_audio_path)
    if not seg_fn:
        raise RuntimeError("RunningHub上传段音频失败")

    node_list = [
        {"nodeId": "3",   "fieldName": "text",  "fieldValue": text},
        {"nodeId": "5",   "fieldName": "audio", "fieldValue": voice_fn},
        {"nodeId": "105", "fieldName": "audio", "fieldValue": seg_fn},
    ]

    task_id = None
    while task_id is None:
        task_id, retryable = await _submit_task(api_url, api_key, clone_workflow_id, node_list)
        if task_id is None and retryable:
            await asyncio.sleep(5)
    print(f"[runninghub:clone] task: {task_id}")

    file_url = await _poll_outputs(api_url, api_key, task_id, timeout)
    if not file_url:
        raise RuntimeError(f"RunningHub克隆任务超时或失败: {task_id}")

    from .config import get_project_dir
    project_dir = get_project_dir(project_id)
    dub_path = project_dir / f"clone_{segment_id[:8]}.wav"
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.get(file_url)
        resp.raise_for_status()
        dub_path.write_bytes(resp.content)
    print(f"[runninghub:clone] done: {dub_path}")
    return str(dub_path)


def check_comfyui_available(api_url: str) -> bool:
    try:
        resp = httpx.get(f"{api_url.rstrip('/')}", timeout=5)
        return resp.status_code < 500
    except Exception:
        return False
