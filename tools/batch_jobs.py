"""List splat jobs from tools/shotlist.json as tab-separated lines: id, place name, videos (comma-joined).

Usage:  python -I tools/batch_jobs.py            all shots with a clip not yet marked as splatted
        python -I tools/batch_jobs.py --done ID  mark ID as splatted
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SHOTLIST = ROOT / "tools" / "shotlist.json"


def main():
    s = json.loads(SHOTLIST.read_text(encoding="utf-8"))
    if "--done" in sys.argv:
        sid = sys.argv[sys.argv.index("--done") + 1]
        for sh in s["shots"]:
            if sh["id"] == sid:
                sh["status"] = "splat"
                sh["splat"] = f"public/assets/splats/{sid}-fit.ply"
        SHOTLIST.write_text(json.dumps(s, indent=2, ensure_ascii=False), encoding="utf-8")
        return
    for sh in s["shots"]:
        videos = sh.get("videos") or ([sh["video"]] if sh.get("video") else [])
        videos = [v for v in videos if (ROOT / v).exists()]
        if videos and sh["status"] != "splat":
            sys.stdout.buffer.write(f"{sh['id']}\t{sh['name']}\t{','.join(videos)}\n".encode("utf-8"))


if __name__ == "__main__":
    main()
