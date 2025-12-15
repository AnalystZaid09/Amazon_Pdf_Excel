import streamlit as st
import pdfplumber
import pandas as pd
import re
from io import BytesIO

# ---------------- PAGE CONFIG ---------------- #
st.set_page_config(page_title="Amazon Invoice PDF → Excel", layout="wide")
st.title("📄 Amazon Invoice PDF → Excel Extractor")

# ---------------- PDF EXTRACTION ---------------- #
def extract_pdf(pdf_file):
    rows = []

    with pdfplumber.open(pdf_file) as pdf:
        lines = []

        # Read all lines safely
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                lines.extend([l.strip() for l in text.split("\n") if l.strip()])

        full_text = "\n".join(lines)

        # -------- Invoice-level fields -------- #
        invoice_number = re.search(r"Invoice Number:\s*(\S+)", full_text)
        invoice_period = re.search(r"Invoice Period:\s*(.+)", full_text)
        total_amount = re.search(
            r"Total \(tax included\)\s*INR\s*([\d,\.]+)", full_text
        )

        invoice_number = invoice_number.group(1) if invoice_number else ""
        invoice_period = invoice_period.group(1).strip() if invoice_period else ""
        total_amount = float(total_amount.group(1).replace(",", "")) if total_amount else 0.0

        # -------- STATE-BASED CAMPAIGN PARSER -------- #
        buffer = ""

        for line in lines:
            buffer = f"{buffer} {line}".strip()

            match = re.search(
                r"^(.*?)\s+"
                r"(SPONSORED PRODUCTS|SPONSORED DISPLAY|SPONSORED BRANDS)\s+"
                r"(-?\d+)\s+"
                r"([\d\.]+)\s+INR\s+"
                r"(-?[\d\.]+)\s+INR",
                buffer
            )

            if match:
                rows.append({
                    "Campaign": match.group(1).strip(),
                    "Campaign Type": match.group(2),
                    "Clicks": int(match.group(3)),
                    "Average CPC": float(match.group(4)),
                    "Amount": float(match.group(5)),   # Campaign amount
                    "Invoice Number": invoice_number,
                    "Invoice Period": invoice_period,
                    "Amount (Total Amount)": total_amount
                })

                # Reset only AFTER complete row is captured
                buffer = ""

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
        all_data = []

        for pdf in uploaded_files:
            df = extract_pdf(pdf)
            all_data.append(df)

        final_df = pd.concat(all_data, ignore_index=True)

        if final_df.empty:
            st.error("❌ No campaign data extracted. Please verify PDF format.")
        else:
            st.success("✅ Data extracted successfully")
            st.dataframe(final_df)

            # -------- Excel Export -------- #
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
