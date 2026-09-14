#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""QA_runner_K 대시보드 단독 실행 프로그램 (QA_Runner_K_Dashboard.exe). [NEW v0.6.0]

대시보드는 원래 본 프로그램(QA_Runner_K.exe) 안에서 돌기 때문에 프로그램을 닫으면 같이 꺼진다.
"프로그램을 안 켠 상태에서도 대시보드를 보고 TC를 정리하고 싶다"는 요청에 따라,
대시보드만 따로 띄우는 작은 실행 파일을 분리했다.

  - 자동화(Playwright/Chromium)가 필요 없으므로 본 프로그램보다 훨씬 가볍다
  - 결과 DB와 스크린샷은 exe와 같은 폴더를 쓰므로, 본 프로그램과 같은 폴더에 두면
    동일한 데이터를 본다 (results_store._base_dir() 기준)
  - 여기서 추가/수정한 TC는 본 프로그램이 "대시보드 추가 TC" 소스로 그대로 실행한다

TC 실행 자체는 브라우저 자동화가 필요해서 본 프로그램에서만 가능하다.
"""

import sys
import threading
import tkinter as tk
import webbrowser
from tkinter import ttk

import dashboard_server
import results_store

APP_TITLE = "QA_runner_K 대시보드"


def _open(url):
    try:
        webbrowser.open(url)
    except Exception:
        pass


def main(open_browser=True, minimized=False):
    """[v0.8.0] open_browser/minimized는 '부팅 시 자동 시작'(--quiet)을 위한 것.
    부팅할 때마다 브라우저 탭이 열리고 창이 튀어나오면 성가시므로, 자동 시작에서는
    서버만 조용히 올리고 창은 작업표시줄에 내려둔다."""
    # 이미 떠 있으면(본 프로그램이 띄웠거나, 이 프로그램이 이미 실행 중이면) 새로 띄우지 않는다
    existing = dashboard_server.find_running_dashboard()
    if existing:
        host, port = existing
        url = f"http://{host}:{port}/"
        if open_browser:
            _open(url + "tcs")
        # 이미 떠 있는데 조용한 모드면(= 부팅 자동 시작인데 본 프로그램이 먼저 떴다면)
        # 창까지 띄울 이유가 없으니 그냥 끝낸다
        if minimized:
            return
        _show_window(url, already_running=True)
        return

    try:
        host, port = dashboard_server.run_in_background(db_path=results_store.get_db_path())
    except Exception as e:
        if minimized:
            return          # 자동 시작 실패는 조용히 포기 (부팅 때 오류창이 뜨면 곤란)
        _show_error(f"대시보드를 시작하지 못했습니다.\n\n{e}")
        return

    url = f"http://{host}:{port}/"
    if open_browser:
        _open(url + "tcs")
    _show_window(url, already_running=False, minimized=minimized)


def _show_window(url, already_running, minimized=False):
    root = tk.Tk()
    root.title(APP_TITLE)
    root.geometry("470x210")
    root.resizable(False, False)
    if minimized:
        root.iconify()

    frm = ttk.Frame(root, padding=16)
    frm.pack(fill="both", expand=True)

    head = "이미 실행 중인 대시보드에 연결했습니다" if already_running else "대시보드를 실행했습니다"
    ttk.Label(frm, text=head, font=("Malgun Gothic", 11, "bold")).pack(anchor="w")
    ttk.Label(frm, text="브라우저가 안 열렸으면 아래 주소를 복사해서 들어가세요.",
              foreground="#555").pack(anchor="w", pady=(4, 8))

    url_var = tk.StringVar(value=url)
    entry = ttk.Entry(frm, textvariable=url_var, width=52)
    entry.pack(anchor="w")
    entry.select_range(0, "end")

    btns = ttk.Frame(frm)
    btns.pack(anchor="w", pady=12)
    ttk.Button(btns, text="TC 관리 열기", command=lambda: _open(url + "tcs")).pack(side="left")
    ttk.Button(btns, text="실행 결과 열기", command=lambda: _open(url)).pack(side="left", padx=6)
    ttk.Button(btns, text="종료", command=root.destroy).pack(side="left")

    note = ("이 창을 닫으면 대시보드도 함께 종료됩니다."
            if not already_running else
            "이 대시보드는 다른 프로그램이 띄운 것이라, 이 창을 닫아도 계속 열려 있습니다.")
    ttk.Label(frm, text=note + "  ·  TC 실행은 QA_Runner_K.exe에서 합니다.",
              foreground="#777", wraplength=430).pack(anchor="w")

    root.mainloop()


def _show_error(message):
    root = tk.Tk()
    root.title(APP_TITLE)
    root.geometry("430x170")
    frm = ttk.Frame(root, padding=16)
    frm.pack(fill="both", expand=True)
    ttk.Label(frm, text="오류", font=("Malgun Gothic", 11, "bold")).pack(anchor="w")
    ttk.Label(frm, text=message, wraplength=390, foreground="#a3271c").pack(anchor="w", pady=8)
    ttk.Button(frm, text="닫기", command=root.destroy).pack(anchor="w")
    root.mainloop()


if __name__ == "__main__":
    main()
