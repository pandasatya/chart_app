import frappe
import os
import pandas as pd
from frappe.utils.file_manager import save_file
from frappe.utils import random_string
import json


@frappe.whitelist()  # allow_guest if you want to call it without authentication
def upload_and_process_file():
    # Get the uploaded file
    if 'file' not in frappe.request.files:
        frappe.throw("File is required")

    file = frappe.request.files['file']

    # Save the uploaded file temporarily in the private/files folder
    file_doc = save_file(file.filename, file.read(), "File", random_string(10), is_private=1)

    # Full path to the uploaded file
    file_path = os.path.join(frappe.get_site_path(), 'private', 'files', file_doc.file_name)

    # Read the CSV file into a DataFrame
    # Read the CSV file into a DataFrame
    try:
        df = pd.read_csv(file_path, encoding='utf-8')  # Default to utf-8 encoding
    except UnicodeDecodeError:
        # If there's an encoding error, try using a different encoding, like ISO-8859-1
        df = pd.read_csv(file_path, encoding='ISO-8859-1')

    columns = list(df.columns)
    data = df.to_dict(orient="records")

    # Dynamically create a DocType and insert data
    doctype_name = create_dynamic_doctype(file.filename, columns)
    insert_data_into_doctype(doctype_name, data)

    # Prepare data for chart
    chart_data = prepare_chart_data(df)

    # Return the chart data and the name of the newly created DocType
    return json.dumps({
        "status": "success",
        "doctype": doctype_name,  # Return the name of the newly created DocType
        "chart_data": chart_data  # Return the formatted data for charting
    })

import re

def create_dynamic_doctype(file_name, columns):
    """
    Create a new DocType based on the columns of the uploaded CSV file.
    Sanitize the columns to remove any special characters that aren't allowed in fieldnames.
    """
    doctype_name = f"Data_{file_name.replace('.csv', '').replace('.xlsx', '')}_{random_string(5)}"
    
    if not frappe.db.exists("DocType", doctype_name):
        # Sanitize the columns to be valid fieldnames
        fields = []
        for col in columns:
            sanitized_fieldname = re.sub(r'\W+', '_', col.lower())  # Replace special characters with underscores
            sanitized_fieldname = sanitized_fieldname.strip('_')  # Remove leading/trailing underscores

            # Ensure the fieldname doesn't start with a number
            if sanitized_fieldname[0].isdigit():
                sanitized_fieldname = f"_{sanitized_fieldname}"

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


def insert_data_into_doctype(doctype_name, data):
    """
    Insert data into the newly created DocType dynamically.
    """
    for row in data:
        doc = frappe.get_doc({"doctype": doctype_name})
        
        for field, value in row.items():
            doc.set(field.lower().replace(" ", "_"), value)
        
        doc.insert()

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

