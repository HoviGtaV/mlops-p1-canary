"""Builds REPORT.html and REPORT.pdf from REPORT.md (Windows: prints with headless Microsoft Edge).

    python report/build_pdf.py          (needs: pip install markdown)
"""
import os
import pathlib
import re
import subprocess
import time

import markdown

HERE = pathlib.Path(__file__).resolve().parent
CSS = """
body{font-family:'Segoe UI',Arial,sans-serif;max-width:820px;margin:24px auto;font-size:10.5pt;
     line-height:1.45;color:#1a1a1a}
h1{font-size:20pt;border-bottom:2px solid #1f4e79;padding-bottom:4px;color:#1f4e79}
h2{font-size:14pt;color:#1f4e79;margin-top:22px}
h3{font-size:11.5pt}
table{border-collapse:collapse;margin:8px 0;font-size:9.5pt}
th,td{border:1px solid #bbb;padding:3px 7px;text-align:left}
th{background:#e8eef5}
img{max-width:100%;display:block;margin:10px auto}
p,li,table,img,.keep{break-inside:avoid;page-break-inside:avoid}
code{background:#f2f2f2;padding:0 3px;font-size:9pt}
@page{size:A4;margin:14mm}
"""


def main():
    md = (HERE / "REPORT.md").read_text(encoding="utf-8")
    body = markdown.markdown(md, extensions=["tables"])
    # Keep every heading on the same page as the block that follows it.
    body = re.sub(r"(<h[23][^>]*>.*?</h[23]>)\s*(<(p|table|ul|ol)>.*?</\3>)",
                  r'<div class="keep">\1\2</div>', body, flags=re.S)
    html = ("<!doctype html><html><head><meta charset='utf-8'><title>P1 Canary report</title>"
            f"<style>{CSS}</style></head><body>{body}</body></html>")
    (HERE / "REPORT.html").write_text(html, encoding="utf-8")

    edge = next(p for p in [r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"]
                if os.path.exists(p))
    pdf = HERE / "REPORT.pdf"
    pdf.unlink(missing_ok=True)
    subprocess.run([edge, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                    f"--print-to-pdf={pdf}", (HERE / "REPORT.html").as_uri()],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    for _ in range(20):
        if pdf.exists() and pdf.stat().st_size > 0:
            break
        time.sleep(0.5)
    print("wrote", pdf if pdf.exists() else "NOTHING (Edge failed)")


if __name__ == "__main__":
    main()
