from __future__ import annotations

from io import BytesIO

import pandas as pd
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt


def _add_table(doc: Document, df: pd.DataFrame, columns: list[str], limit: int = 15) -> None:
    view = df.loc[:, [c for c in columns if c in df.columns]].head(limit).copy()
    table = doc.add_table(rows=1, cols=len(view.columns))
    table.style = "Table Grid"
    for idx, col in enumerate(view.columns):
        table.rows[0].cells[idx].text = str(col)
    for _, row in view.iterrows():
        cells = table.add_row().cells
        for idx, value in enumerate(row):
            cells[idx].text = "—" if pd.isna(value) else (f"{value:.2f}" if isinstance(value, float) else str(value))


def build_report(fund: str, period: str, summary: dict, changes: pd.DataFrame,
                 themes: pd.DataFrame, peers: pd.DataFrame, notes: str, source: str) -> bytes:
    doc = Document()
    title = doc.add_heading("基金分析報告", 0)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.add_run(f"{fund}　{period}").bold = True

    doc.add_heading("投資結論", level=1)
    doc.add_paragraph(summary["conclusion"])
    doc.add_heading("基金規模與風險", level=1)
    metrics = pd.DataFrame({"項目": list(summary["metrics"].keys()), "數值": list(summary["metrics"].values())})
    _add_table(doc, metrics, ["項目", "數值"], 20)

    doc.add_heading("區間持股變化", level=1)
    _add_table(doc, changes, ["ticker", "name", "動作", "期初權重", "期末權重", "權重變化"], 20)
    doc.add_heading("投資題材", level=1)
    _add_table(doc, themes, ["theme", "期初權重", "期末權重", "權重變化"], 15)

    doc.add_heading("獲利貢獻", level=1)
    winners = changes.sort_values("估計貢獻", ascending=False)
    _add_table(doc, winners, ["ticker", "name", "區間報酬", "估計貢獻"], 10)
    doc.add_heading("虧損拖累", level=1)
    _add_table(doc, winners.sort_values("估計貢獻"), ["ticker", "name", "區間報酬", "估計貢獻"], 10)

    doc.add_heading("同類基金比較", level=1)
    _add_table(doc, peers, ["基金", "區間報酬", "年化波動", "最大回撤", "Sharpe"], 15)
    doc.add_heading("補充說明", level=1)
    doc.add_paragraph(notes or "無")
    doc.add_paragraph(f"資料來源：{source or '使用者上傳資料'}")
    doc.add_paragraph("本報告為量化整理工具，不構成投資建議。持股貢獻採平均權重乘區間報酬估算，與基金正式歸因可能不同。")

    for section in doc.sections:
        section.header.paragraphs[0].text = "基金分析報告產生器"
    for style in doc.styles:
        if hasattr(style, "font"):
            style.font.name = "Arial"
            if style.name == "Normal":
                style.font.size = Pt(10.5)
    output = BytesIO()
    doc.save(output)
    return output.getvalue()

