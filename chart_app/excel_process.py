import frappe
import os
import json
import pandas as pd
import re
import requests
from frappe.utils.file_manager import save_file
from frappe.utils import random_string

@frappe.whitelist()
def upload_and_process_excel():
    """Handles file upload, processes Excel file, creates DocType, and returns chart data."""
    
    # Check if file is uploaded
    if 'file' not in frappe.request.files:
        frappe.throw("File is required")

    file = frappe.request.files['file']

    # Ensure it's an Excel file
    if not file.filename.endswith((".xlsx", ".xls")):
        frappe.throw("Please upload an Excel (.xlsx or .xls) file")

    # Save the uploaded file temporarily in the private/files folder
    file_doc = save_file(file.filename, file.read(), "File", random_string(10), is_private=1)

    # Full path to the uploaded file
    file_path = os.path.join(frappe.get_site_path(), 'private', 'files', file_doc.file_name)

    # Read the Excel file into a DataFrame
    try:
        df = pd.read_excel(file_path, engine='openpyxl')  # Ensure openpyxl is used for .xlsx
    except Exception as e:
        frappe.throw(f"Error reading the Excel file: {str(e)}")

    columns = [str(col) for col in df.columns]  # Convert all column names to strings
    data = df.to_dict(orient="records")

    # Create a new DocType dynamically and insert data
    doctype_name = create_dynamic_doctype(file.filename, columns)
    insert_data_into_doctype(doctype_name, data)

    # Prepare data for chart
    chart_data = prepare_chart_data(df)

    # Return success response
    return json.dumps({
        "status": "success",
        "doctype": doctype_name,
        "chart_data": chart_data
    })

def create_dynamic_doctype(file_name, columns):
    """
    Create a new DocType dynamically based on Excel columns.
    """
    doctype_name = f"Data_{file_name.replace('.xlsx', '').replace('.xls', '')}_{random_string(5)}"
    
    if not frappe.db.exists("DocType", doctype_name):
        fields = []
        for col in columns:
            sanitized_fieldname = re.sub(r'\W+', '_', str(col).lower()).strip('_')

            # Ensure the fieldname doesn't start with a number
            if sanitized_fieldname and sanitized_fieldname[0].isdigit():
                sanitized_fieldname = f"_{sanitized_fieldname}"

            if sanitized_fieldname:
                fields.append({
                    "fieldname": sanitized_fieldname,
                    "fieldtype": "Data",
                    "label": col
                })

        doc = frappe.get_doc({
            "doctype": "DocType",
            "name": doctype_name,
            "module": "Custom",
            "custom": 1,
            "fields": fields,
            "autoname": "autoincrement",
            "permissions": [{"role": "System Manager", "read": 1, "write": 1, "create": 1}]
        })
        doc.insert()

    return doctype_name

#def insert_data_into_doctype(doctype_name, data):
#    """
#    Insert Excel data into the dynamically created DocType.
#    """
#    for row in data:
#        doc = frappe.get_doc({"doctype": doctype_name})
#        for field, value in row.items():
#            doc.set(str(field).lower().replace(" ", "_"), value)
#        doc.insert()

def insert_data_into_doctype(doctype_name, data):
    """
    Insert Excel data into the dynamically created DocType.
    """
    for row in data:
        doc = frappe.get_doc({"doctype": doctype_name})
        for field, value in row.items():
            # Convert NaN values to None
            if pd.isna(value):  
                value = None  

            doc.set(str(field).lower().replace(" ", "_"), value)

        doc.insert()


def prepare_chart_data(df):
    """
    Prepare chart data from the Excel DataFrame.
    """
    chart_labels = df.iloc[:, 0].tolist()  # Get labels from the first column
    chart_datasets = {}

    for col in df.columns[1:]:
        data = df[col].tolist()
        chart_datasets[col] = {
            "data": data,
            "backgroundColor": get_random_color()
        }

    return {
        "labels": chart_labels,
        "datasets": [{"label": key, "data": value["data"], "backgroundColor": value["backgroundColor"]}
                     for key, value in chart_datasets.items()]
    }

def get_random_color():
    """
    Generate a random RGB color for chart datasets.
    """
    import random
    return f'rgba({random.randint(0, 255)}, {random.randint(0, 255)}, {random.randint(0, 255)}, 0.5)'

# OpenAI SQL Query Generation Functions
openai_api_token = frappe.db.get_single_value('Digital Insights Settings', 'open_api_token')

@frappe.whitelist(allow_guest=True)
def get_dataset(user_query):
    """
    Fetch dataset using OpenAI-generated SQL query.
    """
    doctype_name = frappe.db.get_value("Tab Doctype", {}, "name", order_by="creation desc")
    table_schema = get_table_schema(doctype_name)
    sql_query = get_openai_response(user_query, table_schema)
    return sql_query

def get_table_schema(doctype):
    """
    Get the table schema dynamically from Frappe.
    """
    table_name = f"tab{doctype}"
    schema = frappe.db.sql(f"DESCRIBE `{table_name}`", as_dict=True)
    
    table_schema = f"""Table: {table_name}\nColumns:"""
    
    for column in schema:
        column_type = column['Type'].upper()
        if 'varchar' in column_type: column_type = 'VARCHAR'
        elif 'int' in column_type: column_type = 'INT'
        elif 'float' in column_type: column_type = 'FLOAT'
        elif 'date' in column_type: column_type = 'DATE'
        elif 'text' in column_type: column_type = 'TEXT'
        
        table_schema += f'\n- {column["Field"]} ({column_type})'
    
    return table_schema

def get_openai_response(user_query, table_schema):
    """
    Use OpenAI API to generate SQL query from natural language.
    """
    headers = {
        "Authorization": f"Bearer {openai_api_token}",
    }
    response = requests.get("https://api.openai.com/v1/dashboard/billing/usage", headers=headers)
    return response.json() if response.status_code == 200 else f"Error: {response.status_code} - {response.text}"
