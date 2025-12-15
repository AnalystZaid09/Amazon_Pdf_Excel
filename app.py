import camelot
import pandas as pd
import re
import os

PDF_FOLDER = "pdfs"
OUTPUT_FILE = "Amazon_Invoice_Data.xlsx"

def extract_invoice(pdf_path):
    rows = []

    tables = camelot.read_pdf(
        pdf_path,
        pages="all",
        flavor="lattice",
        strip_text="\n"
    )

    text_tables = camelot.read_pdf(pdf_path, pages="1", flavor="stream")
    full_text = " ".join(text_tables[0].df.astype(str).values.flatten())

    invoice_number = re.search(r"Invoice Number:\s*(\S+)", full_text)
    invoice_period = re.search(r"Invoice Period:\s*(.+?)Payment", full_text)
    total_amount = re.search(r"Total \(tax included\)\s*INR\s*([\d,\.]+)", full_text)

    invoice_number = invoice_number.group(1) if invoice_number else ""
    invoice_period = invoice_period.group(1).strip() if invoice_period else ""
    total_amount = float(total_amount.group(1).replace(",", "")) if total_amount else 0.0

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
                rows.append({
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

    return rows

all_rows = []

for file in os.listdir(PDF_FOLDER):
    if file.lower().endswith(".pdf"):
        all_rows.extend(extract_invoice(os.path.join(PDF_FOLDER, file)))

df = pd.DataFrame(all_rows)
df.to_excel(OUTPUT_FILE, index=False)

print("✅ Excel generated:", OUTPUT_FILE)
