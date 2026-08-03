import argparse
import os
import time

import requests


def submit_task(base_url: str, file_path: str, user_id: str) -> dict:
    """提交一个解析任务。"""
    with open(file_path, "rb") as f:
        response = requests.post(
            f"{base_url}/parse-md",
            files={"file": (os.path.basename(file_path), f)},
            data={"user_id": user_id},
            timeout=60,
        )
    response.raise_for_status()
    return response.json()


def get_status(base_url: str, task_id: str) -> dict:
    """查询一个解析任务状态。"""
    response = requests.get(f"{base_url}/parse-md/{task_id}", timeout=30)
    response.raise_for_status()
    return response.json()


def main() -> None:
    parser = argparse.ArgumentParser(description="Test async MinerU Markdown API.")
    parser.add_argument("files", nargs="+", help="Files to submit.")
    parser.add_argument("--url", default="http://127.0.0.1:8010", help="API base URL.")
    parser.add_argument("--user-id", default="anonymous", help="User id.")
    parser.add_argument("--interval", type=float, default=3.0, help="Polling interval seconds.")
    args = parser.parse_args()

    tasks = {}
    for file_path in args.files:
        result = submit_task(args.url.rstrip("/"), file_path, args.user_id)
        task_id = result["task_id"]
        tasks[task_id] = file_path
        print(f"submitted {task_id} <- {file_path} status={result.get('status')} progress={result.get('progress')}")

    finished = set()
    while len(finished) < len(tasks):
        for task_id, file_path in tasks.items():
            if task_id in finished:
                continue
            status = get_status(args.url.rstrip("/"), task_id)
            state = status.get("status")
            progress = status.get("progress")
            message = status.get("message")
            print(f"{task_id} {state} {progress}% {message}")
            if state in {"done", "failed"}:
                finished.add(task_id)
                if state == "done":
                    print(f"  markdown_url: {status.get('markdown_url')}")
                    print(f"  content chars: {len(status.get('content') or '')}")
                else:
                    print(f"  error: {status.get('error')}")
        if len(finished) < len(tasks):
            time.sleep(args.interval)


if __name__ == "__main__":
    main()
