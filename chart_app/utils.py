import frappe
import os
import pandas as pd
from frappe.utils.file_manager import save_file
from frappe.utils import random_string
import json
from chart_app.excel_process import upload_and_process_excel

@frappe.whitelist()
def upload_and_process_file():
    # Get the uploaded file
    if 'file' not in frappe.request.files:
        frappe.throw("File is required")

    file = frappe.request.files['file']
    file_name = file.filename
    file_extension = os.path.splitext(file_name)[1].lower()

    # Save the uploaded file temporarily in the private/files folder
    file_doc = save_file(file_name, file.read(), "File", random_string(10), is_private=1)

    # Full path to the uploaded file
    file_path = os.path.join(frappe.get_site_path(), 'private', 'files', file_doc.file_name)

    # Read the file into a DataFrame based on file type
    df = None
    
    try:
        if file_extension in ['.csv']:
            # Try multiple approaches for CSV files
            encoding_options = ['utf-8', 'ISO-8859-1', 'latin1', 'cp1252']
            parser_error = None
            
            for encoding in encoding_options:
                try:
                    # Try with different delimiters and error handling
                    df = pd.read_csv(
                        file_path, 
                        encoding=encoding,
                        on_bad_lines='skip',  # Skip problematic lines
                        sep=None,  # Auto-detect separator
                        engine='python'  # More flexible python engine
                    )
                    break  # If successful, exit the loop
                except UnicodeDecodeError:
                    continue  # Try next encoding
                except pd.errors.ParserError as e:
                    parser_error = str(e)
                    continue  # Try next encoding
                except Exception as e:
                    parser_error = str(e)
                    continue  # Try next encoding
            
            # If we couldn't parse with any encoding, try a more aggressive approach
            if df is None:
                try:
                    # Try with the C engine and a specific delimiter
                    df = pd.read_csv(
                        file_path,
                        encoding='ISO-8859-1',  # Most permissive encoding
                        sep=',',               # Explicitly use comma
                        quoting=3,             # QUOTE_NONE
                        engine='c'             # Faster C engine
                    )
                except Exception as e:
                    if parser_error:
                        frappe.throw(f"Could not parse CSV file: {parser_error}")
                    else:
                        frappe.throw(f"Error reading CSV file: {str(e)}")
                        
        elif file_extension in ['.xlsx', '.xls']:
            try:
                # For Excel files, try with different engines
                df = pd.read_excel(file_path, engine='openpyxl')
            except Exception as e:
                try:
                    # If openpyxl fails, try with xlrd
                    df = pd.read_excel(file_path, engine='xlrd')
                except Exception as e2:
                    frappe.throw(f"Error reading Excel file: {str(e2)}")
        else:
            frappe.throw(f"Unsupported file format: {file_extension}. Please upload a CSV or Excel file.")
    
    except Exception as e:
        frappe.throw(f"Unexpected error processing file: {str(e)}")
    
    # If still None, we couldn't process the file
    if df is None:
        frappe.throw("Unable to process the file. Please check the file format and try again.")
    
    # Clean up column names to ensure they're strings
    df.columns = df.columns.astype(str)
    
    # Remove any completely empty columns or rows
    df = df.dropna(how='all', axis=1).dropna(how='all', axis=0)
    
    columns = list(df.columns)
    data = df.to_dict(orient="records")

    # Dynamically create a DocType and insert data
    doctype_name = create_dynamic_doctype(file_name, columns)
    insert_data_into_doctype(doctype_name, data)

    # Prepare data for chart
    chart_data = prepare_chart_data(df)

    # Return the chart data and the name of the newly created DocType
    return json.dumps({
        "status": "success",
        "doctype": doctype_name,  # Return the name of the newly created DocType
        "chart_data": chart_data,  # Return the formatted data for charting
        "columns": columns,        # Return the column names
        "row_count": len(data)     # Return the number of rows processed
    })

import re

def create_dynamic_doctype(file_name, columns):
    """
    Create a new DocType based on the columns of the uploaded file.
    Sanitize the columns to remove any special characters that aren't allowed in fieldnames.
    """
    # Remove any file extension (.csv, .xlsx, .xls) from the filename
    base_name = os.path.splitext(file_name)[0]
    # Further sanitize the base name
    base_name = re.sub(r'\W+', '_', base_name)
    doctype_name = f"Data_{base_name}_{random_string(5)}"
    
    if not frappe.db.exists("DocType", doctype_name):
        # Sanitize the columns to be valid fieldnames
        fields = []
        used_fieldnames = set()  # Track used fieldnames to avoid duplicates
        
        for col in columns:
            # Ensure column name is a string and has a reasonable length
            col_str = str(col)[:140]  # Limit length to avoid issues
            
            sanitized_fieldname = re.sub(r'\W+', '_', col_str.lower())  # Replace special characters with underscores
            sanitized_fieldname = sanitized_fieldname.strip('_')  # Remove leading/trailing underscores

            # Ensure the fieldname doesn't start with a number
            if sanitized_fieldname and sanitized_fieldname[0].isdigit():
                sanitized_fieldname = f"_{sanitized_fieldname}"
                
            # Handle empty or invalid fieldnames
            if not sanitized_fieldname:
                sanitized_fieldname = f"field_{len(fields)}"
                
            # Ensure fieldname is unique
            original_fieldname = sanitized_fieldname
            counter = 1
            while sanitized_fieldname in used_fieldnames:
                sanitized_fieldname = f"{original_fieldname}_{counter}"
                counter += 1
                
            used_fieldnames.add(sanitized_fieldname)

            fields.append({
                "fieldname": sanitized_fieldname,
                "fieldtype": "Data",
                "label": col_str
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
        
        try:
            doc.insert()
        except Exception as e:
            frappe.log_error(f"Error creating DocType {doctype_name}: {str(e)}")
            frappe.throw(f"Error creating DocType: {str(e)}")

    return doctype_name

def insert_data_into_doctype(doctype_name, data):
    """
    Insert data into the newly created DocType dynamically.
    """
    doctype_fields = frappe.get_meta(doctype_name).fields
    field_map = {field.label: field.fieldname for field in doctype_fields if field.fieldtype == "Data"}
    
    for row in data:
        try:
            doc = frappe.get_doc({"doctype": doctype_name})
            
            for field, value in row.items():
                # Handle NaN values from pandas DataFrame
                if pd.isna(value):
                    value = None
                elif isinstance(value, (float, int)):
                    # Convert numeric values to strings to avoid potential issues
                    value = str(value)
                    
                # Use the fieldname mapping from labels to ensure correct field assignment
                if field in field_map:
                    doc.set(field_map[field], value)
                else:
                    # Fallback to direct setting with sanitized field name
                    sanitized_field = re.sub(r'\W+', '_', str(field).lower()).strip('_')
                    if sanitized_field and sanitized_field[0].isdigit():
                        sanitized_field = f"_{sanitized_field}"
                    
                    if sanitized_field and hasattr(doc, sanitized_field):
                        doc.set(sanitized_field, value)
            
            doc.insert(ignore_permissions=True)
        except Exception as e:
            frappe.log_error(f"Error inserting row into {doctype_name}: {str(e)}")
            # Continue with next row instead of failing completely
            continue
        
        
@frappe.whitelist()
def handle_file_upload():
    if 'file' not in frappe.request.files:
        frappe.throw("File is required")

    file = frappe.request.files['file']
    file_extension = os.path.splitext(file.filename)[1].lower()

    if file_extension == ".csv":
        return upload_and_process_file()
    elif file_extension in [".xlsx", ".xls"]:
        return upload_and_process_excel(file)
    else:
        frappe.throw("Invalid file type. Please upload a CSV or Excel file.")


# @frappe.whitelist()  # allow_guest if you want to call it without authentication
# def upload_and_process_file():
#     # Get the uploaded file
#     if 'file' not in frappe.request.files:
#         frappe.throw("File is required")

#     file = frappe.request.files['file']

#     # Save the uploaded file temporarily in the private/files folder
#     file_doc = save_file(file.filename, file.read(), "File", random_string(10), is_private=1)

#     # Full path to the uploaded file
#     file_path = os.path.join(frappe.get_site_path(), 'private', 'files', file_doc.file_name)

#     # Read the CSV file into a DataFrame
#     # Read the CSV file into a DataFrame
#     try:
#         df = pd.read_csv(file_path, encoding='utf-8')  # Default to utf-8 encoding
#     except UnicodeDecodeError:
#         # If there's an encoding error, try using a different encoding, like ISO-8859-1
#         df = pd.read_csv(file_path, encoding='ISO-8859-1')

#     columns = list(df.columns)
#     data = df.to_dict(orient="records")

#     # Dynamically create a DocType and insert data
#     doctype_name = create_dynamic_doctype(file.filename, columns)
#     insert_data_into_doctype(doctype_name, data)

#     # Prepare data for chart
#     chart_data = prepare_chart_data(df)

#     # Return the chart data and the name of the newly created DocType
#     data=json.dumps({
#         "status": "success",
#         "doctype": doctype_name,  # Return the name of the newly created DocType
#         "chart_data": chart_data  # Return the formatted data for charting
#     })
#     json_string = data
#     return json.loads(json_string)
#     #datas["message"] = json.loads(datas["message"])
#     #formatted_json = json.dumps(datas, indent=2)
#     #return datas

# import re

# def create_dynamic_doctype(file_name, columns):
#     """
#     Create a new DocType based on the columns of the uploaded CSV file.
#     Sanitize the columns to remove any special characters that aren't allowed in fieldnames.
#     """
#     doctype_name = f"Data_{file_name.replace('.csv', '').replace('.xlsx', '')}_{random_string(5)}"
    
#     if not frappe.db.exists("DocType", doctype_name):
#         # Sanitize the columns to be valid fieldnames
#         fields = []
#         for col in columns:
#             sanitized_fieldname = re.sub(r'\W+', '_', col.lower())  # Replace special characters with underscores
#             sanitized_fieldname = sanitized_fieldname.strip('_')  # Remove leading/trailing underscores

#             # Ensure the fieldname doesn't start with a number
#             if sanitized_fieldname[0].isdigit():
#                 sanitized_fieldname = f"_{sanitized_fieldname}"

#             fields.append({
#                 "fieldname": sanitized_fieldname,
#                 "fieldtype": "Data",
#                 "label": col
#             })

#         doc = frappe.get_doc({
#             "doctype": "DocType",
#             "name": doctype_name,
#             "module": "Custom",
#             "custom": 1,
#             "fields": fields,
#             "autoname": "autoincrement",
#             "permissions": [{"role": "System Manager", "read": 1, "write": 1, "create": 1}]
#         })
#         doc.insert()

#     return doctype_name


# def insert_data_into_doctype(doctype_name, data):
#     """
#     Insert data into the newly created DocType dynamically.
#     """
#     for row in data:
#         doc = frappe.get_doc({"doctype": doctype_name})
        
#         for field, value in row.items():
#             doc.set(field.lower().replace(" ", "_"), value)
        
#         doc.insert()

def prepare_chart_data(df):
    """
    Prepare chart data from the DataFrame.
    Assumes the first column contains categories and the rest contain values.
    """
    chart_labels = df.iloc[:, 0].tolist()  # Get labels from the first column

    chart_datasets = {}

    for col in df.columns[1:]:
        data = df[col].tolist()
        
        # Add to datasets dictionary
        chart_datasets[col] = {
            "data": data,
            "backgroundColor": get_random_color()  # Optional: Generate a random color for the dataset
        }

    # Format the final chart data for output
    final_chart_data = {
        "labels": chart_labels,
        "datasets": [{"label": key, "data": value["data"], "backgroundColor": value["backgroundColor"]}
                     for key, value in chart_datasets.items()]
    }

    return final_chart_data

def get_random_color():
    """
    Generate a random RGB color for chart datasets.
    """
    import random
    return f'rgba({random.randint(0, 255)}, {random.randint(0, 255)}, {random.randint(0, 255)}, 0.5)'


import openai
import frappe
import requests

# OpenAI API Key (secure this in System Settings or Environment Variable)
openai.api_key = "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" #frappe.db.get_single_value('System Settings', 'openai_api_key')

import openai

# Function to generate SQL query based on user query and table schema
def get_sql_query(user_query, table_schema):
    models = openai.Model.list()
    # return models
    messages = [
        {"role": "system", "content": "You are a helpful assistant that converts natural language queries into SQL queries."},
        {"role": "user", "content": f"Convert the following natural language query into a SQL query that fetches relevant data from the provided table:\n\nTable Schema:\n{table_schema}\n\nUser Query: {user_query}"}
    ]

    # # create a chat completion
    # chat_completion = openai.ChatCompletion.create(model="gpt-4o-mini", messages=[{"role": "user", "content": "Hello world"}])

    # # Prepare messages for the OpenAI ChatCompletion
    
    # return (chat_completion.choices[0].message.content)

    try:
        # Use gpt-3.5-turbo or gpt-4 if available
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",  # Change to "gpt-4" if you have access
            messages=messages
        )

        # Extract the SQL query from the response
        sql_query = response['choices'][0]['message']['content'].strip()
        
        if not sql_query:  # Check if the sql_query is empty or None
            raise ValueError("Generated SQL query is empty or None.")

        return sql_query
    except Exception as e:
        print(f"Error occurred during SQL generation: {e}")
        return None




@frappe.whitelist(allow_guest=True)
def get_dataset(user_query):
    # Define your table schema (can be dynamically fetched from Frappe's Doctype definition)
    # table_schema = """
    # Table: tabData_saless_G7cGd
    # Columns:
    # - name (VARCHAR)
    # - date (DATE)
    # - product_name (VARCHAR)
    # - quantity (INT)
    # - price (FLOAT)
    # """
    table_schema=get_table_schema("Data_saless_G7cGd")
    # return table_schema

    # # Generate SQL Query using OpenAI
    sql_query = get_openai_response(user_query, table_schema)

    # # Execute SQL Query in Frappe and return the dataset
    # result = frappe.db.sql(sql_query, as_dict=True)

    # # Return the dataset as a list of dictionaries (JSON format)
    return sql_query


def get_table_schema(doctype):
    # Prepare the table name (tables in Frappe are prefixed with 'tab')
    table_name = f"tab{doctype}"
    
    # Execute SQL query to get the table schema
    schema = frappe.db.sql(f"DESCRIBE `{table_name}`", as_dict=True)
    
    # Start building the table schema string
    table_schema = f'"""\nTable: {table_name}\nColumns:'
    
    for column in schema:
        # Formatting the column type (converting MySQL types to general SQL types)
        column_type = column['Type'].upper()
        
        if 'varchar' in column_type:
            column_type = 'VARCHAR'
        elif 'int' in column_type:
            column_type = 'INT'
        elif 'float' in column_type:
            column_type = 'FLOAT'
        elif 'date' in column_type:
            column_type = 'DATE'
        elif 'text' in column_type:
            column_type = 'TEXT'
        
        # Append the column information in the required format
        table_schema += f'\n- {column["Field"]} ({column_type})'
    
    # End of schema string
    table_schema += '\n"""'
    
    # Return or print the table schema
    return table_schema



import json

# Replace with your OpenAI API key
OPENAI_API_KEY = "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" #"sk-UA7ukqcRX82-UIiyta1m6qyMDsdu9CI7j-9kAbcU9pT3BlbkFJv0hyVTQ7lWCPux2rKwiX8X71boaBKcerOKKvEkbuoA"


def get_openai_response(user_query, table_schema):
    # url = "https://api.openai.com/v1/chat/completions"

    # headers = {
    #     "Content-Type": "application/json",
    #     "Authorization": f"Bearer {OPENAI_API_KEY}",
    # }

    # # Prepare the payload
    # messages = [
    #     {"role": "system", "content": "You are a helpful assistant that converts natural language queries into SQL queries."},
    #     {"role": "user", "content": f"Convert the following natural language query into a SQL query:\n\nTable Schema:\n{table_schema}\n\nUser Query: {user_query}"}
    # ]

    # data = {
    #     "model": "gpt-3.5-turbo-0125",
    #     "messages": messages
    # }

    # # Make the API request
    # response = requests.post(url, headers=headers, data=json.dumps(data))
    # return response.json()
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
    }

    response = requests.get("https://api.openai.com/v1/dashboard/billing/usage", headers=headers)

    if response.status_code == 200:
        usage_data = response.json()
        return (usage_data)  # Print the usage data
    else:
        return (f"Error: {response.status_code} - {response.text}")

    # if response.status_code == 200:
    #     return response.json()
    # else:
    #     print(f"Error: {response.status_code} - {response.text}")
    #     return None

