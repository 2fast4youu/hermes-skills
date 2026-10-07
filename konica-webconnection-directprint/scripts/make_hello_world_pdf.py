#!/usr/bin/env python3
"""Create a one-page Hello World PDF for direct-print smoke tests."""
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
import argparse, os

parser = argparse.ArgumentParser()
parser.add_argument("output", nargs="?", default="/tmp/hello_world_test.pdf")
parser.add_argument("--text", default="Hello World")
args = parser.parse_args()

out = os.path.abspath(args.output)
c = canvas.Canvas(out, pagesize=A4)
w, h = A4
c.setFont("Helvetica-Bold", 42)
c.drawCentredString(w / 2, h / 2, args.text)
c.showPage()
c.save()
print(out)
