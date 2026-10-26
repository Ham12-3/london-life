"""Move splat training to a Colab GPU and back.

  python -I tools/colab_transfer.py pack      zip solved places (poses.ok, not yet splatted) into
                                              work/colab-up/batch-N.zip files under 9.5 MB each
  python -I tools/colab_transfer.py unpack Z  take a splats-*.zip downloaded from Colab: each <id>.ply
                                              goes to public/assets/splats, is fitted to the map
                                              (align_splat.py) and marked done in the shot list

The upload holds only what training needs: the frames plus a slimmed COLMAP text model
(cameras, poses, point positions and colours; per-point tracks are dropped).
"""
import io
import json
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / "work"
UP = WORK / "colab-up"
LIMIT = int(9.5 * 1024 * 1024)


def jobs():
    s = json.loads((ROOT / "tools" / "shotlist.json").read_text(encoding="utf-8"))
    return {sh["id"]: sh for sh in s["shots"]}


def slim_model(model):
    out = {"cameras.txt": (model / "cameras.txt").read_text()}
    lines = [l for l in (model / "images.txt").read_text().splitlines() if l and not l.startswith("#")]
    out["images.txt"] = "".join(f"{pose}\n0 0 -1\n" for pose in lines[0::2])
    pts = []
    for l in (model / "points3D.txt").read_text().splitlines():
        if l and not l.startswith("#"):
            pts.append(" ".join(l.split()[:8]))
    out["points3D.txt"] = "\n".join(pts) + "\n"
    return out


def pack():
    UP.mkdir(parents=True, exist_ok=True)
    shots = jobs()
    sent = {l.strip() for l in (UP / "sent.txt").read_text().splitlines()} if (UP / "sent.txt").exists() else set()
    ready = [d.name for d in sorted(WORK.iterdir()) if (d / "poses.ok").exists() and d.name in shots
             and shots[d.name]["status"] != "splat" and d.name not in sent]
    batch, size, n = [], 0, len(list(UP.glob("batch-*.zip")))
    blobs = {}
    for sid in ready:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as zf:
            for name, text in slim_model(WORK / sid / "sparse" / "0").items():
                zf.writestr(f"{sid}/sparse/0/{name}", text)
            for img in sorted((WORK / sid / "images").glob("*.jpg")):
                zf.write(img, f"{sid}/images/{img.name}")
        blobs[sid] = buf.getvalue()

    def flush():
        nonlocal batch, size, n
        if not batch:
            return
        n += 1
        path = UP / f"batch-{n:02d}.zip"
        with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED) as zf:
            for sid in batch:
                with zipfile.ZipFile(io.BytesIO(blobs[sid])) as inner:
                    for item in inner.namelist():
                        zf.writestr(item, inner.read(item))
        print(f"{path.name}: {len(batch)} places, {path.stat().st_size / 1e6:.1f} MB: {', '.join(batch)}")
        with open(UP / "sent.txt", "a") as fh:
            fh.write("".join(f"{sid}\n" for sid in batch))
        batch, size = [], 0

    for sid in ready:
        if size + len(blobs[sid]) > LIMIT:
            flush()
        batch.append(sid)
        size += len(blobs[sid])
    flush()
    if not ready:
        print("nothing new to pack")


def unpack(zpath):
    shots = jobs()
    splats = ROOT / "public" / "assets" / "splats"
    with zipfile.ZipFile(zpath) as zf:
        names = [n for n in zf.namelist() if n.endswith(".ply")]
        for name in names:
            sid = Path(name).stem
            if sid not in shots:
                print(f"skip {name}: unknown shot")
                continue
            (splats / f"{sid}.ply").write_bytes(zf.read(name))
            r = subprocess.run([sys.executable, "-P", str(ROOT / "tools" / "align_splat.py"), sid, shots[sid]["name"]],
                               capture_output=True, text=True, encoding="utf-8")
            if r.returncode:
                print(f"{sid}: fit FAILED {r.stderr.strip()[-200:]}")
                continue
            subprocess.run([sys.executable, "-I", str(ROOT / "tools" / "batch_jobs.py"), "--done", sid], check=True)
            kept = [l for l in r.stdout.splitlines() if l.startswith("kept")]
            print(f"{sid}: {kept[0] if kept else 'fitted'}")


if __name__ == "__main__":
    if sys.argv[1:2] == ["pack"]:
        pack()
    elif sys.argv[1:2] == ["unpack"]:
        unpack(sys.argv[2])
    else:
        print(__doc__)
