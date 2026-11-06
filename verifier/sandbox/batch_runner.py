#!/usr/bin/env python3
"""In-container batch runner (stdlib only; runs inside the sandbox image).

Usage: python3 batch_runner.py /jobs/job.json

For every case in the job: create a fresh working directory, copy the case's input files in, run
the command with the case's stdin/args/env (and frozen time if requested), enforce a wall-clock
timeout and a file-size limit, then record stdout, stderr, return code, every file left in the
working directory, and (optionally) the GnuCOBOL trace. Optionally run each case twice and flag
disagreements (flakiness).

Layout:  <inputs_root>/<case>/{case.json,stdin.txt,in/...}   (read-only)
         <results_root>/<case>/{stdout,stderr,return_code,meta.json,trace.txt,out/...}
"""

from __future__ import annotations

import concurrent.futures
import hashlib
import json
import os
import resource
import shutil
import signal
import subprocess
import sys
import time

STDERR_CAP = 1024 * 1024


def _sha(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _snapshot(root: str) -> dict[str, str]:
    files: dict[str, str] = {}
    for dirpath, _dirs, names in os.walk(root):
        for n in names:
            full = os.path.join(dirpath, n)
            if os.path.islink(full) or not os.path.isfile(full):
                continue
            files[os.path.relpath(full, root)] = _sha(full)
    return dict(sorted(files.items()))


def _limits(fsize: int) -> None:
    resource.setrlimit(resource.RLIMIT_FSIZE, (fsize, fsize))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def _run_once(job: dict, case_id: str, case: dict, rep: int) -> dict:
    inputs_dir = os.path.join(job["inputs_root"], case_id)
    workdir = os.path.join("/tmp/run", f"{case_id}-r{rep}")
    shutil.rmtree(workdir, ignore_errors=True)
    os.makedirs(workdir)
    in_dir = os.path.join(inputs_dir, "in")
    if os.path.isdir(in_dir):
        shutil.copytree(in_dir, workdir, dirs_exist_ok=True)
    capture = os.path.join("/tmp/capture", f"{case_id}-r{rep}")
    os.makedirs(capture, exist_ok=True)

    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": "/tmp", "LANG": "C.UTF-8",
           "LC_ALL": "C.UTF-8", "TZ": "UTC"}
    env.update(job.get("env", {}))
    env.update(case.get("env", {}))
    fake = case.get("fake_time") or job.get("force_fake_time")
    if fake:
        env["LD_PRELOAD"] = job["faketime_lib"]
        env["FAKETIME"] = fake.replace("T", " ")
        env["FAKETIME_DONT_FAKE_MONOTONIC"] = "1"
        env["COBOL_VERIFIER_FAKE_TIME"] = fake
    trace_path = None
    if job.get("trace"):
        trace_path = os.path.join(capture, "trace.txt")
        env["COB_SET_TRACE"] = "Y"
        env["COB_TRACE_FILE"] = trace_path
        env["COB_TRACE_FORMAT"] = job["trace"]["format"]

    argv = list(job["command"]) + [str(a) for a in case.get("args", [])]
    stdin_path = os.path.join(inputs_dir, case.get("stdin", "stdin.txt"))
    out_path = os.path.join(capture, "stdout")
    err_path = os.path.join(capture, "stderr")
    timed_out = False
    start = time.monotonic()
    with open(out_path, "wb") as out, open(err_path, "wb") as err:
        stdin = open(stdin_path, "rb") if os.path.exists(stdin_path) else subprocess.DEVNULL
        try:
            proc = subprocess.Popen(
                argv, cwd=workdir, env=env, stdin=stdin, stdout=out, stderr=err,
                start_new_session=True, preexec_fn=lambda: _limits(job["fsize_bytes"]),
            )
            try:
                rc = proc.wait(timeout=job["timeout_s"])
            except subprocess.TimeoutExpired:
                timed_out = True
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                rc = proc.wait()
        finally:
            if stdin is not subprocess.DEVNULL:
                stdin.close()
    duration = time.monotonic() - start
    stdout_size = os.path.getsize(out_path)
    stdout_truncated = stdout_size > job["stdout_cap"]
    if stdout_truncated:
        with open(out_path, "r+b") as fh:
            fh.truncate(job["stdout_cap"])
    if os.path.getsize(err_path) > STDERR_CAP:
        with open(err_path, "r+b") as fh:
            fh.truncate(STDERR_CAP)
    return {
        "workdir": workdir,
        "capture": capture,
        "trace": trace_path if trace_path and os.path.exists(trace_path) else None,
        "returncode": rc,
        "signal": -rc if rc < 0 else None,
        "timed_out": timed_out,
        "duration_s": round(duration, 4),
        "stdout_truncated": stdout_truncated,
        "stdout_sha": _sha(out_path),
        "files": _snapshot(workdir),
    }


def _run_case(job: dict, case_id: str) -> dict:
    results = os.path.join(job["results_root"], case_id)
    shutil.rmtree(results, ignore_errors=True)
    os.makedirs(results)
    meta: dict = {"case": case_id}
    try:
        with open(os.path.join(job["inputs_root"], case_id, "case.json"), encoding="utf-8") as fh:
            case = json.load(fh)
        runs = [_run_once(job, case_id, case, rep) for rep in range(max(1, int(job.get("repeat", 1))))]
        first = runs[0]
        shutil.copyfile(os.path.join(first["capture"], "stdout"), os.path.join(results, "stdout"))
        shutil.copyfile(os.path.join(first["capture"], "stderr"), os.path.join(results, "stderr"))
        with open(os.path.join(results, "return_code"), "w", encoding="ascii") as fh:
            fh.write(str(first["returncode"]))
        out_dir = os.path.join(results, "out")
        os.makedirs(out_dir)
        for rel in first["files"]:
            dst = os.path.join(out_dir, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copyfile(os.path.join(first["workdir"], rel), dst)
        if first["trace"]:
            shutil.copyfile(first["trace"], os.path.join(results, "trace.txt"))
        flaky = []
        for r in runs[1:]:
            if r["stdout_sha"] != first["stdout_sha"]:
                flaky.append("stdout")
            if r["returncode"] != first["returncode"]:
                flaky.append("return_code")
            if r["files"] != first["files"]:
                flaky.append("files")
            if r["timed_out"] != first["timed_out"]:
                flaky.append("timeout")
        meta.update({k: first[k] for k in ("returncode", "signal", "timed_out", "duration_s",
                                            "stdout_truncated", "files")})
        meta["runs"] = len(runs)
        meta["flaky"] = sorted(set(flaky))
        meta["fake_time"] = case.get("fake_time") or job.get("force_fake_time")
        for r in runs:
            shutil.rmtree(r["workdir"], ignore_errors=True)
            shutil.rmtree(r["capture"], ignore_errors=True)
    except Exception as exc:  # recorded per case; the host turns this into ERROR, never PASS
        meta["runner_error"] = f"{type(exc).__name__}: {exc}"
    with open(os.path.join(results, "meta.json"), "w", encoding="utf-8") as fh:
        json.dump(meta, fh, indent=1, sort_keys=True)
    return meta


def main() -> int:
    with open(sys.argv[1], encoding="utf-8") as fh:
        job = json.load(fh)
    start = time.monotonic()
    os.makedirs("/tmp/run", exist_ok=True)
    os.makedirs("/tmp/capture", exist_ok=True)
    errors = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, int(job.get("workers", 1)))) as ex:
        for meta in ex.map(lambda c: _run_case(job, c), job["cases"]):
            if "runner_error" in meta:
                errors.append({"case": meta["case"], "error": meta["runner_error"]})
    summary = {"cases": len(job["cases"]), "duration_s": round(time.monotonic() - start, 3),
               "errors": errors}
    with open(os.path.join(job["results_root"], "_batch.json"), "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=1)
    print(json.dumps(summary))
    return 0


if __name__ == "__main__":
    sys.exit(main())
