import streamlit as st
import camelot
import pandas as pd
import re
from io import BytesIO
import tempfile
import os

st.set_page_config(page_title="Amazon Invoice PDF → Excel", layout="wide")
st.title("📄 Amazon Invoice PDF → Excel (Table Accurate)")

def extract_invoice(pdf_path):
    all_rows = []

    # ---- Extract tables (border based) ----
    tables = camelot.read_pdf(
        pdf_path,
        pages="all",
        flavor="lattice",
        strip_text="\n"
    )

    # ---- Extract invoice-level data ----
    text_tables = camelot.read_pdf(pdf_path, pages="1", flavor="stream")
    full_text = " ".join(text_tables[0].df.astype(str).values.flatten())

    invoice_number = re.search(r"Invoice Number:\s*(\S+)", full_text)
    invoice_period = re.search(r"Invoice Period:\s*(.+?)Payment", full_text)
    total_amount = re.search(r"Total \(tax included\)\s*INR\s*([\d,\.]+)", full_text)

    invoice_number = invoice_number.group(1) if invoice_number else ""
    invoice_period = invoice_period.group(1).strip() if invoice_period else ""
    total_amount = float(total_amount.group(1).replace(",", "")) if total_amount else 0.0

    # ---- Parse campaign tables ----
    for table in tables:
        df = table.df

        if df.shape[1] < 5:
            continue

        df.columns = df.iloc[0]
        df = df.iloc[1:]

        if "Campaign" not in df.columns:
            continue

        for _, row in df.iterrows():
            try:
                all_rows.append({
                    "Campaign": row["Campaign"].replace("\n", " ").strip(),
                    "Campaign Type": row["Campaign Type"].strip(),
                    "Clicks": int(row["Clicks"]),
                    "Average CPC": float(row["Average CPC"].replace("INR", "").strip()),
                    "Amount": float(row["Amount"].replace("INR", "").strip()),
                    "Invoice Number": invoice_number,
                    "Invoice Period": invoice_period,
                    "Amount (Total Amount)": total_amount
                })
            except:
                continue

    return pd.DataFrame(all_rows)

# ---------------- UI ----------------
uploaded_files = st.file_uploader(
    "Upload Amazon Invoice PDFs",
    type="pdf",
    accept_multiple_files=True
)

if st.button("🚀 Extract to Excel"):
    if not uploaded_files:
        st.warning("Upload at least one PDF")
    else:
        all_data = []

        for pdf in uploaded_files:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                tmp.write(pdf.read())
                tmp_path = tmp.name

            all_data.append(extract_invoice(tmp_path))
            os.remove(tmp_path)

        final_df = pd.concat(all_data, ignore_index=True)

        st.success("✅ Data extracted exactly like PDF")
        st.dataframe(final_df)

        output = BytesIO()
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            final_df.to_excel(writer, index=False, sheet_name="Campaign_Data")

        st.download_button(
            "⬇️ Download Excel",
            data=output.getvalue(),
            file_name="Amazon_Invoice_Data.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
