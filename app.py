import streamlit as st
import pdfplumber
import pandas as pd
import re
from io import BytesIO

st.set_page_config(page_title="Amazon Invoice PDF → Excel", layout="wide")
st.title("📄 Amazon Invoice PDF → Excel Extractor")

def extract_pdf(pdf_file):
    rows = []

    IGNORE_KEYWORDS = [
        "total (tax included)",
        "campaign charges",
        "portfolio total",
        "summary of",
        "invoice number",
        "invoice date",
        "invoice period",
        "payment type",
        "from ",
        "this is a digitally signed",
        "frequently asked",
    ]

    with pdfplumber.open(pdf_file) as pdf:
        lines = []

        for page in pdf.pages:
            text = page.extract_text()
            if text:
                lines.extend([l.strip() for l in text.split("\n") if l.strip()])

        full_text = "\n".join(lines)

        # -------- Invoice-level fields --------
        invoice_number = re.search(r"Invoice Number:\s*(\S+)", full_text)
        invoice_period = re.search(r"Invoice Period:\s*(.+)", full_text)
        total_amount = re.search(
            r"Total \(tax included\)\s*INR\s*([\d,\.]+)", full_text
        )

        invoice_number = invoice_number.group(1) if invoice_number else ""
        invoice_period = invoice_period.group(1).strip() if invoice_period else ""
        total_amount = float(total_amount.group(1).replace(",", "")) if total_amount else 0.0

        # -------- FINAL STATE-BASED PARSER --------
        buffer = ""

        for line in lines:
            low = line.lower()

            # Skip invoice / summary junk
            if any(k in low for k in IGNORE_KEYWORDS):
                continue

            # Always append until row closes
            buffer = f"{buffer} {line}".strip()

            # Close row ONLY when full tail appears
            match = re.search(
                r"(SPONSORED PRODUCTS|SPONSORED BRANDS|SPONSORED DISPLAY)\s+"
                r"(\d+)\s+"
                r"([\d\.]+)\s+INR\s+"
                r"([\d\.]+)\s+INR$",
                buffer
            )

            if match:
                campaign_name = buffer[:match.start()].strip()

                rows.append({
                    "Campaign": campaign_name,
                    "Campaign Type": match.group(1),
                    "Clicks": int(match.group(2)),
                    "Average CPC": float(match.group(3)),
                    "Amount": float(match.group(4)),
                    "Invoice Number": invoice_number,
                    "Invoice Period": invoice_period,
                    "Amount (Total Amount)": total_amount
                })

                buffer = ""  # reset ONLY here

    return pd.DataFrame(rows)

# ---------------- UI ---------------- #
uploaded_files = st.file_uploader(
    "Upload Amazon Invoice PDFs",
    type="pdf",
    accept_multiple_files=True
)

if st.button("🚀 Extract to Excel"):
    if not uploaded_files:
        st.warning("Please upload at least one PDF")
    else:
        final_df = pd.concat(
            [extract_pdf(pdf) for pdf in uploaded_files],
            ignore_index=True
        )

        if final_df.empty:
            st.error("❌ No campaign data extracted.")
        else:
            st.success("✅ Data extracted correctly")
            st.dataframe(final_df)

            output = BytesIO()
            with pd.ExcelWriter(output, engine="openpyxl") as writer:
                final_df.to_excel(
                    writer,
                    index=False,
                    sheet_name="Campaign_Data"
                )

            st.download_button(
                "⬇️ Download Excel",
                data=output.getvalue(),
                file_name="Amazon_Invoice_Data.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
