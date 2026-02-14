import streamlit as st
import pandas as pd
import pypdf
import pdfplumber
import re
import io

# --- PAGE CONFIG ---
st.set_page_config(
    page_title="Invoice Data Master",
    page_icon="📊",
    layout="wide"
)

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
        r"total\s*amount\s*\(tax\s*included\)\s*([\d,]+\.\d{2})",
        r"total\s*tax\s*included.*?([\d,]+\.\d{2})",
        r"total\s*amount\s*\(tax\s*included\)\s*inr\s*([\d,]+\.\d{2})",
        r"total\s*amount.*?tax\s*included.*?([\d,]+\.\d{2})",
        r"total.*?tax\s*included.*?inr\s*([\d,]+\.\d{2})",
        r"total\s*amount.*?([\d,]+\.\d{2})"
    ]

    for pattern in patterns:
        match = re.search(pattern, flat, re.IGNORECASE)
        if match:
            return float(match.group(1))

    raise ValueError("❌ 'Total Amount (tax included)' not found in invoice")

def process_invoice(pdf_file):
    # Use bytes for both to avoid re-reading
    pdf_bytes = pdf_file.read()
    pdf_file.seek(0)
    
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

                metric_match = re.search(r"(SPONSORED\s+(?:PRODUCTS|BRANDS|DISPLAY))\s+(-?\d+)\s+(-?[\d,.]+)(?:\s*INR)?\s+(-?[\d,.]+)(?:\s*INR)?", line, re.IGNORECASE)
                
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
        
        if not rows:
            raise ValueError("pypdf returned no data")
            
        return rows, "pypdf"

    except Exception as e:
        # Fallback to pdfplumber
        pdf_file.seek(0)
        try:
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                full_text = "\n".join([p.extract_text() or "" for p in pdf.pages])
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
                for page in pdf.pages:
                    table = page.extract_table()
                    if not table:
                        continue
                    
                    name_accum = []
                    
                    for row in table:
                        clean_row = [str(cell).strip() if cell else "" for cell in row]
                        row_str = " ".join(clean_row)
                        
                        metric_match = re.search(
                            r"(SPONSORED\s+(?:PRODUCTS|BRANDS|DISPLAY))\s+(-?\d+)\s+(-?[\d,.]+)(?:\s*INR)?\s+(-?[\d,.]+)(?:\s*INR)?",
                            row_str, re.IGNORECASE
                        )
                        
                        if metric_match:
                            possible_name = row_str[:metric_match.start()].strip()
                            if possible_name:
                                name_accum.append(possible_name)
                            
                            rows.append({
                                "Campaign": clean_campaign_name_final(name_accum),
                                "Campaign Type": metric_match.group(1).upper(),
                                "Clicks": int(metric_match.group(2)),
                                "Average CPC": float(metric_match.group(3).replace(',', '')),
                                "Amount": float(metric_match.group(4).replace(',', '')),
                                "Invoice Number": meta["num"],
                                "Invoice date": meta["date"],
                                "Total Amount (tax included)": meta["total"]
                            })
                            name_accum = []
                        else:
                            if any(k in row_str.upper() for k in ["CAMPAIGN", "CLICKS", "FROM", "TRADE CENTER", "INVOICE NUMBER", "SUMMARY"]):
                                name_accum = []
                                continue
                            if any(c for c in clean_row if c):
                                name_accum.append(row_str)
                
                return rows, ("fallback_success" if rows else "failed")
        except Exception:
            return [], "failed"

# --- STREAMLIT UI ---
st.title("📊 Invoice Data Extractor (Amazon Support Advertisment)")
st.markdown("### Process multiple PDF invoices with brand mapping and comprehensive reporting")
st.markdown("---")

# File uploaders
col1, col2 = st.columns(2)

with col1:
    st.subheader("📁 Step 1: Upload Invoice PDFs")
    uploaded_files = st.file_uploader(
        "Upload all PDF Invoices", 
        type="pdf", 
        accept_multiple_files=True,
        help="Upload one or more invoice PDF files"
    )

with col2:
    st.subheader("📋 Step 2: Upload Portfolio Report")
    portfolio_file = st.file_uploader(
        "Upload Portfolio Report (Excel with Campaign & Brand Columns)",
        type=["xlsx", "xls"],
        help="Excel file containing campaign to brand mapping"
    )

st.markdown("---")

if uploaded_files:
    combined_data = []
    status_history = []
    
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    # Process all invoices
    for i, f in enumerate(uploaded_files):
        status_text.text(f"Processing ({i+1}/{len(uploaded_files)}): {f.name}")
        rows, method = process_invoice(f)
        combined_data.extend(rows)
        status_history.append({"File": f.name, "Status": method, "Rows": len(rows)})
        progress_bar.progress((i + 1) / len(uploaded_files))
    
    status_text.text("✅ Processing Complete!")
    
    # Show processing status
    if status_history:
        with st.expander("📊 View Detailed Processing Report"):
            status_df = pd.DataFrame(status_history)
            st.dataframe(status_df, use_container_width=True)

    if combined_data:
        df = pd.DataFrame(combined_data)
        
        # Add With GST Column
        df["With GST Amount (18%)"] = df["Amount"] * 1.18
        
        # Add Brand using Portfolio Report
        if portfolio_file:
            try:
                portfolio_df = pd.read_excel(portfolio_file)

                # Clean column names
                portfolio_df.columns = (
                    portfolio_df.columns
                    .astype(str)
                    .str.strip()
                    .str.replace("\n", " ", regex=False)
                    .str.replace("\r", " ", regex=False)
                )

                # Detect required columns
                portfolio_col = None
                brand_col = None
                name_col = None

                for col in portfolio_df.columns:
                    col_lower = col.lower()
                    if "portfolio" in col_lower:
                        portfolio_col = col
                    elif "brand" in col_lower:
                        brand_col = col
                    elif col_lower == "name" or col_lower.endswith(" name"):
                        name_col = col

                if portfolio_col and brand_col:
                    # Rename dynamically
                    rename_dict = {
                        portfolio_col: "Campaign",
                        brand_col: "Brand"
                    }

                    if name_col:
                        rename_dict[name_col] = "Name"

                    portfolio_df = portfolio_df.rename(columns=rename_dict)

                    # Clean text for matching
                    def clean_text(x):
                        return str(x).lower().strip()

                    df["Campaign_clean"] = df["Campaign"].apply(clean_text)
                    portfolio_df["Campaign_clean"] = portfolio_df["Campaign"].apply(clean_text)

                    # Keep only Brand & Name
                    keep_cols = ["Campaign_clean", "Brand"]
                    if "Name" in portfolio_df.columns:
                        keep_cols.append("Name")

                    portfolio_df = portfolio_df[keep_cols]
                    portfolio_df = portfolio_df.drop_duplicates("Campaign_clean")

                    # Merge
                    df = df.merge(
                        portfolio_df,
                        on="Campaign_clean",
                        how="left"
                    )

                    # Remove helper column
                    df.drop(columns=["Campaign_clean"], inplace=True)
                    
                    st.success(f"✅ Portfolio mapping complete! {len(df[df['Brand'].notna()])} campaigns matched with brands.")

                    # Show unmatched
                    unmatched = df[df["Brand"].isna()]
                    if not unmatched.empty:
                        st.warning(f"⚠️ {len(unmatched)} campaigns not matched with brands.")
                        with st.expander("View Unmatched Campaigns"):
                            st.dataframe(unmatched[["Campaign"]].drop_duplicates())

                else:
                    st.error("❌ Could not detect Portfolio or Brand column in uploaded file.")

            except Exception as e:
                st.error(f"❌ Portfolio file processing failed: {str(e)}")

        # Final column arrangement
        cols = ["Campaign", "Campaign Type", "Clicks", "Average CPC", "Amount", 
                "Invoice Number", "Invoice date", "Total Amount (tax included)", 
                "With GST Amount (18%)", "Brand", "Name"]
        df = df[[c for c in cols if c in df.columns]]
        
        # Sidebar for brand selection
        st.sidebar.header("🎯 Filter Options")
        
        if "Brand" in df.columns:
            brands = sorted(df["Brand"].dropna().unique().tolist())
            selected_brands = st.sidebar.multiselect(
                "Select Brand(s)",
                options=brands,
                default=brands,
                help="Select one or more brands to filter the data"
            )
        else:
            selected_brands = []
        
        # Create tabs for 3 reports
        tab1, tab2, tab3 = st.tabs(["📋 Master Report", "🔍 Brand Filtered Report", "📊 Pivot Table Report"])
        
        # Helper function for Excel download
        @st.cache_data
        def convert_df_to_excel(dataframe, sheet_name='Report'):
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                dataframe.to_excel(writer, index=False, sheet_name=sheet_name)
            return output.getvalue()
        
        # ============= TAB 1: MASTER REPORT =============
        with tab1:
            st.header("Master Report - All Invoices")
            st.write(f"**Total Records:** {len(df)}")
            st.write(f"**Total Files Processed:** {len(uploaded_files)}")
            
            # Summary metrics
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("Total Campaigns", df["Campaign"].nunique())
            with col2:
                st.metric("Total Clicks", f"{df['Clicks'].sum():,}")
            with col3:
                st.metric("Total Amount", f"₹{df['Amount'].sum():,.2f}")
            with col4:
                st.metric("With GST", f"₹{df['With GST Amount (18%)'].sum():,.2f}")
            
            # Display data
            st.dataframe(df, use_container_width=True, height=400)
            
            # Download button
            excel_data = convert_df_to_excel(df, 'Master Report')
            st.download_button(
                label="📥 Download Master Report (Excel)",
                data=excel_data,
                file_name="invoice_master_report.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
        
        # ============= TAB 2: BRAND FILTERED REPORT =============
        with tab2:
            st.header("Brand Filtered Report")
            
            if "Brand" in df.columns and selected_brands:
                # Filter data
                filtered_df = df[df['Brand'].isin(selected_brands)].copy()
                
                st.write(f"**Selected Brands:** {', '.join(selected_brands)}")
                st.write(f"**Filtered Records:** {len(filtered_df)}")
                
                # Summary metrics
                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    st.metric("Campaigns", filtered_df["Campaign"].nunique())
                with col2:
                    st.metric("Total Clicks", f"{filtered_df['Clicks'].sum():,}")
                with col3:
                    st.metric("Total Amount", f"₹{filtered_df['Amount'].sum():,.2f}")
                with col4:
                    st.metric("With GST", f"₹{filtered_df['With GST Amount (18%)'].sum():,.2f}")
                
                # Display filtered data
                st.dataframe(filtered_df, use_container_width=True, height=400)
                
                # Download button
                filtered_excel = convert_df_to_excel(filtered_df, 'Filtered Report')
                st.download_button(
                    label="📥 Download Filtered Report (Excel)",
                    data=filtered_excel,
                    file_name=f"invoice_filtered_{'_'.join(selected_brands[:3])}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
            elif "Brand" not in df.columns:
                st.warning("⚠️ Please upload a Portfolio Report to enable brand filtering.")
            else:
                st.warning("⚠️ Please select at least one brand from the sidebar.")
        
        # ============= TAB 3: PIVOT TABLE REPORT =============
        with tab3:
            st.header("Pivot Table Report - Brand Summary")
            
            if "Brand" in df.columns:
                # Filter data if brands selected
                if selected_brands:
                    pivot_source_df = df[df['Brand'].isin(selected_brands)].copy()
                else:
                    pivot_source_df = df.copy()
                
                # Create pivot table
                pivot_df = (
                    pivot_source_df.groupby("Brand", dropna=False)
                    .agg({
                        "Campaign": "count",
                        "Clicks": "sum",
                        "Amount": "sum",
                        "With GST Amount (18%)": "sum"
                    })
                    .reset_index()
                    .rename(columns={
                        "Campaign": "Total Campaigns",
                        "Clicks": "Total Clicks",
                        "Amount": "Total Amount (excl. GST)",
                        "With GST Amount (18%)": "Total Amount (incl. GST)"
                    })
                )
                
                # Sort by total amount
                pivot_df = pivot_df.sort_values("Total Amount (incl. GST)", ascending=False)
                
                # Add Grand Total
                grand_total = pd.DataFrame({
                    'Brand': ['Grand Total'],
                    'Total Campaigns': [pivot_df['Total Campaigns'].sum()],
                    'Total Clicks': [pivot_df['Total Clicks'].sum()],
                    'Total Amount (excl. GST)': [pivot_df['Total Amount (excl. GST)'].sum()],
                    'Total Amount (incl. GST)': [pivot_df['Total Amount (incl. GST)'].sum()]
                })
                pivot_df = pd.concat([pivot_df, grand_total], ignore_index=True)
                
                # Display pivot table
                st.dataframe(
                    pivot_df.style.format({
                        'Total Campaigns': '{:,.0f}',
                        'Total Clicks': '{:,.0f}',
                        'Total Amount (excl. GST)': '₹{:,.2f}',
                        'Total Amount (incl. GST)': '₹{:,.2f}'
                    }).background_gradient(
                        subset=['Total Amount (incl. GST)'], 
                        cmap='YlOrRd'
                    ),
                    use_container_width=True,
                    height=400
                )
                
                # Visualizations
                st.subheader("📈 Brand Performance Charts")
                
                chart_data = pivot_df[pivot_df['Brand'] != 'Grand Total'].copy()
                
                if not chart_data.empty:
                    col_a, col_b = st.columns(2)
                    
                    with col_a:
                        st.write("**Total Amount by Brand (incl. GST)**")
                        st.bar_chart(
                            chart_data.set_index('Brand')['Total Amount (incl. GST)'],
                            height=300
                        )
                    
                    with col_b:
                        st.write("**Total Clicks by Brand**")
                        st.bar_chart(
                            chart_data.set_index('Brand')['Total Clicks'],
                            height=300
                        )
                
                # Download pivot table
                pivot_excel = convert_df_to_excel(pivot_df, 'Pivot Table')
                st.download_button(
                    label="📥 Download Pivot Table (Excel)",
                    data=pivot_excel,
                    file_name="invoice_pivot_table.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
            else:
                st.warning("⚠️ Please upload a Portfolio Report to generate pivot table by brand.")
                
    else:
        st.error("❌ No data could be extracted from the uploaded files.")

else:
    # Instructions
    st.info("👆 Please upload PDF invoice files to get started")
    
    st.markdown("""
    ### Instructions:
    
    1. **Upload Invoice PDFs**: Upload one or more Amazon invoice PDF files
    2. **Upload Portfolio Report** (Optional): Excel file containing Campaign and Brand columns for brand mapping
    3. **Process**: The app will extract invoice data and map brands automatically
    4. **View Reports**:
       - **Master Report**: Complete dataset with all invoices
       - **Brand Filtered Report**: Filter by selected brands
       - **Pivot Table Report**: Summary statistics by brand
    5. **Download**: Each report can be downloaded as Excel
    
    ### Features:
    - Automatic campaign name cleaning
    - Total amount extraction from invoice summary
    - Brand mapping from portfolio report
    - GST calculation (18%)
    - Multi-brand filtering
    - Comprehensive reporting
    """)

# Footer
st.markdown("---")
st.markdown("*Invoice Data Master Dashboard (Support Advertisment) - Version 2.0*")
