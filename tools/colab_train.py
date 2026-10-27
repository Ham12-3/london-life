"""GPU splat trainer for Colab (gsplat). Upload this file plus work/colab-up/batch-*.zip to /content, then:

    !pip -q install gsplat imageio && python /content/colab_train.py

Every uploaded scene (<id>/images + <id>/sparse/0 COLMAP text model) is trained and written as a
standard 3DGS .ply with base colour only, pruned to MAX_SPLATS (tools/align_splat.py reads it unchanged). New results
are bundled into /content/splats-<time>.zip for download; bring them home with
`python -I tools/colab_transfer.py unpack <zip>`.
"""
import glob
import os
import sys
import time
import zipfile

import imageio.v3 as iio
import numpy as np
import torch
import torch.nn.functional as F
from gsplat import rasterization
from gsplat.strategy import DefaultStrategy

STEPS = int(os.environ.get("STEPS", 5000))
MAX_SPLATS = int(os.environ.get("MAX_SPLATS", 200_000))  # keeps each file around 11 MB for the browser


def read_colmap(model):
    cams = {}
    for l in open(f"{model}/cameras.txt"):
        if l.startswith("#") or not l.strip():
            continue
        p = l.split()
        cid, mdl, v = int(p[0]), p[1], list(map(float, p[4:]))
        fx, fy, cx, cy = (v[0], v[0], v[1], v[2]) if mdl.startswith("SIMPLE") else (v[0], v[1], v[2], v[3])
        cams[cid] = np.array([[fx, 0, cx], [0, fy, cy], [0, 0, 1]], np.float32)
    lines = [l for l in open(f"{model}/images.txt") if l.strip() and not l.startswith("#")]
    views = []
    for l in lines[0::2]:
        p = l.split()
        qw, qx, qy, qz, tx, ty, tz = map(float, p[1:8])
        R = np.array([[1 - 2 * (qy * qy + qz * qz), 2 * (qx * qy - qz * qw), 2 * (qx * qz + qy * qw)],
                      [2 * (qx * qy + qz * qw), 1 - 2 * (qx * qx + qz * qz), 2 * (qy * qz - qx * qw)],
                      [2 * (qx * qz - qy * qw), 2 * (qy * qz + qx * qw), 1 - 2 * (qx * qx + qy * qy)]], np.float32)
        M = np.eye(4, dtype=np.float32)
        M[:3, :3], M[:3, 3] = R, [tx, ty, tz]
        views.append((p[9], int(p[8]), M))
    xyz, rgb = [], []
    for l in open(f"{model}/points3D.txt"):
        if l.startswith("#") or not l.strip():
            continue
        p = l.split()
        xyz.append(list(map(float, p[1:4])))
        rgb.append(list(map(float, p[4:7])))
    return cams, views, np.array(xyz, np.float32), np.array(rgb, np.float32) / 255.0


def ssim(a, b, k=11, s=1.5):
    g = torch.exp(-(torch.arange(k, device=a.device) - k // 2) ** 2 / (2 * s * s))
    g = g / g.sum()
    w = (g[:, None] * g[None, :]).expand(3, 1, k, k)
    f = lambda x: F.conv2d(x, w, padding=k // 2, groups=3)
    mu_a, mu_b = f(a), f(b)
    va, vb, cov = f(a * a) - mu_a ** 2, f(b * b) - mu_b ** 2, f(a * b) - mu_a * mu_b
    return (((2 * mu_a * mu_b + 1e-4) * (2 * cov + 9e-4)) / ((mu_a ** 2 + mu_b ** 2 + 1e-4) * (va + vb + 9e-4))).mean()


PLY_NAMES = (["x", "y", "z", "nx", "ny", "nz"] + [f"f_dc_{i}" for i in range(3)]
             + ["opacity"] + [f"scale_{i}" for i in range(3)] + [f"rot_{i}" for i in range(4)])


def write_ply(path, data):
    header = ("ply\nformat binary_little_endian 1.0\ncomment Trained with gsplat in Colab\n" + f"element vertex {len(data)}\n"
              + "".join(f"property float {nm}\n" for nm in PLY_NAMES) + "end_header\n")
    with open(path, "wb") as fh:
        fh.write(header.encode())
        fh.write(data.astype(np.float32).tobytes())


def prune(data):
    """Keep the MAX_SPLATS most visible splats (opacity is stored as a logit, column 9)."""
    keep = data[:, 9] > -2.9  # sigmoid > ~0.05
    data = data[keep]
    if len(data) > MAX_SPLATS:
        data = data[np.argsort(-data[:, 9])[:MAX_SPLATS]]
    return data


def save_ply(path, p):
    # Colour is stored as the base (DC) term only: a quarter of the size, and the browser doesn't need
    # view-dependent shading for these clips.
    means = p["means"].detach().cpu().numpy()
    cols = [means, np.zeros_like(means), p["sh0"].detach().cpu().numpy().reshape(len(means), 3),
            p["opacities"].detach().cpu().numpy()[:, None], p["scales"].detach().cpu().numpy(),
            F.normalize(p["quats"].detach(), dim=-1).cpu().numpy()]
    write_ply(path, prune(np.concatenate(cols, axis=1)))


def slim_existing(path):
    """Rewrite a .ply from an earlier (full-SH, unpruned) run in the slim layout."""
    raw = open(path, "rb").read()
    end = raw.index(b"end_header\n") + len(b"end_header\n")
    names = [l.split()[-1] for l in raw[:end].decode().splitlines() if l.startswith("property")]
    if names == PLY_NAMES:
        return
    data = np.frombuffer(raw[end:], np.float32).reshape(-1, len(names))
    write_ply(path, prune(data[:, [names.index(n) for n in PLY_NAMES]]))


def train(scene_dir, out_path, steps):
    dev = "cuda"
    cams, views, xyz, rgb = read_colmap(f"{scene_dir}/sparse/0")
    imgs, viewmats, Ks = [], [], []
    for name, cid, M in views:
        im = iio.imread(f"{scene_dir}/images/{name}")[..., :3]
        imgs.append(torch.from_numpy(im).float().div(255))
        viewmats.append(torch.from_numpy(M))
        Ks.append(torch.from_numpy(cams[cid]))
    imgs, viewmats, Ks = torch.stack(imgs).to(dev), torch.stack(viewmats).to(dev), torch.stack(Ks).to(dev)
    H, W = imgs.shape[1:3]
    centres = torch.linalg.inv(viewmats)[:, :3, 3]
    scene_scale = float((centres - centres.mean(0)).norm(dim=1).max()) * 1.1 + 1e-6
    pts = torch.from_numpy(xyz).to(dev)
    d = torch.cdist(pts, pts)
    d.fill_diagonal_(1e9)
    knn = d.topk(3, largest=False).values.mean(1).clamp_min(1e-7)
    n = len(pts)
    params = torch.nn.ParameterDict({
        "means": torch.nn.Parameter(pts),
        "scales": torch.nn.Parameter(knn.log()[:, None].repeat(1, 3)),
        "quats": torch.nn.Parameter(torch.rand(n, 4, device=dev)),
        "opacities": torch.nn.Parameter(torch.logit(torch.full((n,), 0.1, device=dev))),
        "sh0": torch.nn.Parameter(((torch.from_numpy(rgb).to(dev) - 0.5) / 0.28209479177387814)[:, None, :]),
        "shN": torch.nn.Parameter(torch.zeros(n, 15, 3, device=dev)),
    })
    lrs = {"means": 1.6e-4 * scene_scale, "scales": 5e-3, "quats": 1e-3, "opacities": 5e-2, "sh0": 2.5e-3, "shN": 2.5e-3 / 20}
    opts = {k: torch.optim.Adam([{"params": params[k], "lr": lr, "name": k}], eps=1e-15) for k, lr in lrs.items()}
    # A higher growth threshold than gsplat's default keeps splat counts browser-sized.
    strategy = DefaultStrategy(verbose=False, refine_stop_iter=int(steps * 0.8), reset_every=max(1000, steps // 2),
                               grow_grad2d=0.0004)
    strategy.check_sanity(params, opts)
    state = strategy.initialize_state(scene_scale=scene_scale)
    decay = 0.01 ** (1 / steps)
    loss = torch.tensor(0.0)
    for step in range(steps):
        i = torch.randint(len(imgs), (1,)).item()
        colors = torch.cat([params["sh0"], params["shN"]], 1)
        out, _, info = rasterization(params["means"], params["quats"], params["scales"].exp(), params["opacities"].sigmoid(),
                                     colors, viewmats[i:i + 1], Ks[i:i + 1], W, H, sh_degree=0, packed=False)
        strategy.step_pre_backward(params, opts, state, step, info)
        pred, gt = out[0].permute(2, 0, 1)[None], imgs[i].permute(2, 0, 1)[None]
        loss = 0.8 * F.l1_loss(pred, gt) + 0.2 * (1 - ssim(pred, gt))
        loss.backward()
        strategy.step_post_backward(params, opts, state, step, info, packed=False)
        for o in opts.values():
            o.step()
            o.zero_grad(set_to_none=True)
        for g in opts["means"].param_groups:
            g["lr"] *= decay
    save_ply(out_path, params)
    return len(params["means"]), float(loss)


def main():
    print(torch.cuda.get_device_name(0) if torch.cuda.is_available() else "NO GPU", flush=True)
    os.makedirs("/content/scenes", exist_ok=True)
    os.makedirs("/content/out", exist_ok=True)
    for z in glob.glob("/content/batch-*.zip"):
        with zipfile.ZipFile(z) as zf:
            zf.extractall("/content/scenes")
        os.remove(z)
    todo = sorted(d for d in os.listdir("/content/scenes") if not os.path.exists(f"/content/out/{d}.ply"))
    print(len(todo), "scenes:", ", ".join(todo), flush=True)
    for sid in todo:
        t = time.time()
        try:
            n, loss = train(f"/content/scenes/{sid}", f"/content/out/{sid}.ply", STEPS)
            print(f"{sid}: {n} splats, loss {loss:.4f}, {time.time() - t:.0f}s", flush=True)
        except Exception as e:  # keep going; one bad scene shouldn't stop the batch
            print(f"{sid}: FAILED {e!r}", flush=True)
        torch.cuda.empty_cache()
    fresh = [f for f in sorted(glob.glob("/content/out/*.ply")) if not os.path.exists(f + ".sent")]
    for f in fresh:
        slim_existing(f)
    if fresh:
        zpath = f"/content/splats-{int(time.time())}.zip"
        with zipfile.ZipFile(zpath, "w", zipfile.ZIP_STORED) as zf:
            for f in fresh:
                zf.write(f, os.path.basename(f))
                open(f + ".sent", "w").close()
        print("RESULT", zpath, len(fresh), "splats", flush=True)


if __name__ == "__main__":
    sys.exit(main())
