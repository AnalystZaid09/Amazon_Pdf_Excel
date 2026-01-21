# Original -gem_updated.py
import streamlit as st
import pandas as pd
import pypdf
import pdfplumber
import re
import io

# --- DATA ENGINEERING LOGIC ---

def clean_campaign_name_final(name_list):
    """Joins fragments and strictly removes 'Exclusive)' noise."""
    full_name = " ".join(name_list).strip()
    
    # Cleaning patterns for 'Exclusive)' and common PDF noise
    noise_patterns = [
        r"\(?Exclusive\)?",              # Removes 'Exclusive)', '(Exclusive)', etc.
        r"Total amount billed.*INR",
        r"Total adjustments.*INR",
        r"Total amount tax included.*INR",
        r"Portfolio name.*?:",
        r"Page \d+ of \d+",
        r"Amazon Seller Services.*",
        r"8th Floor, Brigade GateWay.*",
        r"Trade Center, No 26/1.*",
        r"Dr Raj Kumar Road.*",
        r"Malleshwaram.*",
        r"Bangalore, Karnataka.*",
        r"Summary of Portfolio Charges.*",
        r"Campaign\s+Campaign Type\s+Clicks.*"
    ]
    
    for pattern in noise_patterns:
        full_name = re.sub(pattern, "", full_name, flags=re.IGNORECASE)
    
    return full_name.replace("  ", " ").strip(" :,\"")

def get_total_amount_from_bottom(pdf_obj):
    """
    Extracts 'Total Amount (tax included)' from ANY invoice layout.
    Handles boxes, tables, line breaks, INR before/after value.
    """

    full_text = ""
    # Try pypdf first
    try:
        for page in pdf_obj.pages:
            text = page.extract_text()
            if text:
                full_text += text + "\n"
    except Exception:
        # Fallback if pypdf fails (e.g. KeyError: 'bbox')
        full_text = ""
        # We need to re-open with pdfplumber if pdf_obj is from pypdf
        # But this function is called with different objects now.
        # Let's simplify: the caller should handle the fallback if possible,
        # or we try to detect the object type.
        if hasattr(pdf_obj, 'stream'): # Likely pypdf
            try:
                with pdfplumber.open(pdf_obj.stream) as pl_pdf:
                    for page in pl_pdf.pages:
                        full_text += page.extract_text() + "\n"
            except: pass
        else: # Likely pdfplumber or similar
            for page in pdf_obj.pages:
                full_text += (page.extract_text() or "") + "\n"


    # Normalize text
    flat = (
        full_text
        .replace("\n", " ")
        .replace("\r", " ")
        .replace(",", "")
        .lower()
    )

    patterns = [
        # Total Amount (tax included) 2418.16 INR
        r"total\s*amount\s*\(tax\s*included\)\s*([\d]+\.\d{1,2})",

        # Total Amount tax included 2418.16
        r"total\s*amount\s*tax\s*included\s*([\d]+\.\d{1,2})",

        # Total Amount (tax included)\s+INR\s+2418.16
        r"total\s*amount\s*\(tax\s*included\)\s*inr\s*([\d]+\.\d{1,2})",

        # Box format: Total Amount (tax included)   2418.16 INR
        r"total\s*amount.*?tax\s*included.*?([\d]+\.\d{1,2})\s*inr",

        # Fallback – last occurrence near bottom
        r"total\s*amount.*?([\d]+\.\d{1,2})\s*inr"
    ]

    for pattern in patterns:
        match = re.search(pattern, flat, re.IGNORECASE)
        if match:
            return float(match.group(1))

    raise ValueError("❌ 'Total Amount (tax included)' not found in invoice")



def process_invoice(pdf_file):
    # Use bytes for both to avoid re-reading
    pdf_bytes = pdf_file.read()
    pdf_file.seek(0) # Reset for potential re-read if needed
    
    # Try with pypdf first for accuracy
    try:
        reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
        final_total = get_total_amount_from_bottom(reader)
        
        first_page_text = reader.pages[0].extract_text() or ""
        first_page_text = first_page_text.replace('\n', ' ')
        
        inv_num = re.search(r"Invoice Number\s*[:\s]*(\S+)", first_page_text)
        inv_date = re.search(r"Invoice Date\s*[:\s]*(\d{2}-\d{2}-\d{4})", first_page_text)
        
        meta = {
            "num": inv_num.group(1).strip() if inv_num else "N/A",
            "date": inv_date.group(1).strip() if inv_date else "N/A",
            "total": float(final_total)
        }
        
        rows = []
        name_accum = []
        is_table = False

        for page in reader.pages:
            text = page.extract_text()
            if not text: continue
            lines = text.split('\n')
            for line in lines:
                line = line.strip()
                if "Campaign" in line and "Clicks" in line:
                    is_table = True
                    name_accum = [] 
                    continue
                
                if not is_table: continue

                metric_match = re.search(r"(SPONSORED\s+(?:PRODUCTS|BRANDS|DISPLAY))\s+(-?\d+)\s+(-?[\d,.]+)\s*INR\s+(-?[\d,.]+)\s*INR", line)
                
                if metric_match:
                    name_part = line[:metric_match.start()].strip()
                    if name_part:
                        name_accum.append(name_part)
                    
                    rows.append({
                        "Campaign": clean_campaign_name_final(name_accum),
                        "Campaign Type": metric_match.group(1),
                        "Clicks": int(metric_match.group(2)),
                        "Average CPC": float(metric_match.group(3).replace(',', '')),
                        "Amount": float(metric_match.group(4).replace(',', '')),
                        "Invoice Number": meta["num"],
                        "Invoice date": meta["date"],
                        "Total Amount (tax included)": meta["total"]
                    })
                    name_accum = []
                else:
                    if any(k in line for k in ["FROM", "Trade Center", "Invoice Number", "Summary"]):
                        name_accum = []
                        continue
                    name_accum.append(line)
        # Trigger fallback if no rows found (silent extraction failure)
        if not rows:
            raise ValueError("pypdf returned no data")
            
        return rows

    except Exception as e:
        # Fallback to pdfplumber for robustness
        pdf_file.seek(0)
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            final_total = get_total_amount_from_bottom(pdf)
            
            first_page_text = (pdf.pages[0].extract_text() or "").replace('\n', ' ')
            inv_num = re.search(r"Invoice Number\s*[:\s]*(\S+)", first_page_text)
            inv_date = re.search(r"Invoice Date\s*[:\s]*(\d{2}-\d{2}-\d{4})", first_page_text)
            
            meta = {
                "num": inv_num.group(1).strip() if inv_num else "N/A",
                "date": inv_date.group(1).strip() if inv_date else "N/A",
                "total": float(final_total)
            }
            
            rows = []
            name_accum = []
            is_table = False

            for page in pdf.pages:
                text = page.extract_text()
                if not text: continue
                lines = text.split('\n')
                for line in lines:
                    line = line.strip()
                    if "Campaign" in line and "Clicks" in line:
                        is_table = True
                        name_accum = [] 
                        continue
                    
                    if not is_table: continue

                    metric_match = re.search(r"(SPONSORED\s+(?:PRODUCTS|BRANDS|DISPLAY))\s+(-?\d+)\s+(-?[\d,.]+)\s*INR\s+(-?[\d,.]+)\s*INR", line)
                    
                    if metric_match:
                        name_part = line[:metric_match.start()].strip()
                        if name_part:
                            name_accum.append(name_part)
                        
                        rows.append({
                            "Campaign": clean_campaign_name_final(name_accum),
                            "Campaign Type": metric_match.group(1),
                            "Clicks": int(metric_match.group(2)),
                            "Average CPC": float(metric_match.group(3).replace(',', '')),
                            "Amount": float(metric_match.group(4).replace(',', '')),
                            "Invoice Number": meta["num"],
                            "Invoice date": meta["date"],
                            "Total Amount (tax included)": meta["total"]
                        })
                        name_accum = []
                    else:
                        if any(k in line for k in ["FROM", "Trade Center", "Invoice Number", "Summary"]):
                            name_accum = []
                            continue
                        name_accum.append(line)
        return rows

# --- STREAMLIT UI ---
st.set_page_config(page_title="Invoice Data Master", layout="wide")
st.title("📂 Multi-Invoice Master (Fixed Total & Name Cleaning)")
st.info("Resolved: Pulling Total Amount from the Bottom Summary and removing 'Exclusive)' prefix.")

uploaded_files = st.file_uploader("Upload all PDF Invoices", type="pdf", accept_multiple_files=True)

if uploaded_files:
    combined_data = []
    for f in uploaded_files:
        with st.status(f"Processing {f.name}..."):
            combined_data.extend(process_invoice(f))
    
    if combined_data:
        df = pd.DataFrame(combined_data)
        # Final Format alignment
        df = df[["Campaign", "Campaign Type", "Clicks", "Average CPC", "Amount", 
                 "Invoice Number", "Invoice date", "Total Amount (tax included)"]]
        
        st.success(f"Successfully processed {len(uploaded_files)} files.")
        st.dataframe(df, width='stretch')

        buffer = io.BytesIO()
        df.to_excel(buffer, index=False)
        st.download_button("📥 Download Master Excel", buffer.getvalue(), "Combined_Invoices.xlsx")
