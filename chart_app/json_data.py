import frappe
import json
import requests
from frappe.utils import random_string

# Define reserved keywords
RESERVED_KEYWORDS = [
    "meta", "doctype", "name", "parent", "owner", "modified", "idx", "creation", 
    "modified_by", "parentfield", "parenttype", "docstatus", "naming_series"
]

@frappe.whitelist(allow_guest=True)
def upload_and_process_json():
    # Fetch JSON data from the provided URL
    url = "https://dummyjson.com/products"
    response = requests.get(url)

    if response.status_code != 200:
        frappe.throw("Failed to fetch data from the provided URL")

    # Load JSON data with exception handling
    try:
        data = response.json()
    except json.JSONDecodeError as e:
        frappe.throw(f"JSON decode error: {str(e)}")
    
    if not data or 'products' not in data:
        frappe.throw("No product data found in the JSON response")

    # Extract the product list
    products = data['products']

    # Dynamically extract keys and assign field types based on the first record
    columns, child_tables = determine_columns(products)

    # Dynamically create a DocType and insert data
    doctype_name = create_dynamic_doctype(columns, child_tables)
    insert_data_into_doctype(doctype_name, products, child_tables)

    # Prepare and return data for chart generation
    chart_data = prepare_chart_data(products)

    return {
        "status": "success",
        "doctype": doctype_name,
        "chart_data": chart_data  # Return chart data
    }

def sanitize_fieldname(fieldname):
    """
    Sanitize the fieldname to avoid conflicts with reserved keywords or invalid names.
    """
    sanitized = fieldname.lower().replace(" ", "_")
    
    if sanitized in RESERVED_KEYWORDS:
        sanitized = f"{sanitized}_field"  # Append '_field' to avoid conflict

    return sanitized

def determine_columns(data):
    """
    Determine the columns and their appropriate field types based on the first data entry.
    """
    columns = {}
    child_tables = {}
    first_row = data[0] if data else {}

    for key, value in first_row.items():
        fieldname = sanitize_fieldname(key)

        # Determine the field type dynamically
        if isinstance(value, list):
            # For lists, create a child table
            child_table_name = f"{fieldname}_child"
            child_tables[fieldname] = child_table_name
            columns[fieldname] = "Table"  # Field type as Table
        elif isinstance(value, bool):
            columns[fieldname] = "Check"  # Store booleans as Check (checkbox)
        elif isinstance(value, int):
            columns[fieldname] = "Int"  # Store integers as Int
        elif isinstance(value, float):
            columns[fieldname] = "Float"  # Store floats as Float
        else:
            columns[fieldname] = "Data"  # Default to Data for strings or other values

    return columns, child_tables

def create_dynamic_doctype(columns, child_tables):
    """
    Create a new DocType based on the keys of the JSON data.
    """
    # Ensure unique DocType name by appending a random string
    doctype_name = f"Product_Data_{random_string(5)}"

    if not frappe.db.exists("DocType", doctype_name):
        try:
            # Create child tables
            for child_table_name in child_tables.values():
                create_child_table(child_table_name)

            # Define the fields dynamically from the keys of the JSON
            fields = []
            for fieldname, fieldtype in columns.items():
                field = {
                    "fieldname": fieldname, 
                    "fieldtype": fieldtype, 
                    "label": fieldname.replace("_", " ").title()
                }

                # If the field is a Table, set the child table options
                if fieldtype == "Table":
                    field["options"] = child_tables[fieldname]  # Link to child DocType

                # Set Data field length to 250 characters
                if fieldtype == "Data":
                    field["length"] = 250  # Set max length for Data fields

                # Set Text fields to Long Text for larger values
                if fieldtype == "Text":
                    field["fieldtype"] = "Long Text"  # Use Long Text for larger text fields

                fields.append(field)

            # Create the DocType dynamically
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

        except frappe.exceptions.DuplicateEntryError as e:
            frappe.log_error(f"Duplicate DocType error: {str(e)}")
            return doctype_name  # Return existing name or handle as needed

    return doctype_name

def create_child_table(child_table_name):
    """
    Create a child table for storing list data.
    """
    try:
        # Create child DocType with a Data field set to 250 character length
        child_fields = [{
            "fieldname": "value",
            "fieldtype": "Data",
            "label": "Value",
            "length": 250  # Set max length for Data field
        }]
        
        child_doc = frappe.get_doc({
            "doctype": "DocType",
            "name": child_table_name,
            "module": "Custom",
            "istable": 1,  # This makes it a child table
            "custom": 1,
            "fields": child_fields,
            "autoname": "autoincrement",
            "permissions": [{"role": "System Manager", "read": 1, "write": 1, "create": 1}]
        })
        child_doc.insert()
        return child_doc.name

    except frappe.exceptions.DuplicateEntryError as e:
        frappe.log_error(f"Duplicate child table error: {str(e)}")
        return child_table_name  # Return existing name or handle as needed

def insert_data_into_doctype(doctype_name, data, child_tables):
    """
    Insert data into the specified DocType dynamically.
    """
    for row in data:
        # Create a new document for each row
        doc = frappe.get_doc({"doctype": doctype_name})

        # Map the values from the JSON to the fields in the DocType
        for field, value in row.items():
            field_name = sanitize_fieldname(field)

            if isinstance(value, list):
                # Handle list values for child tables
                if field_name in child_tables:
                    child_table_name = child_tables[field_name]
                    child_entries = []
                    for item in value:
                        if isinstance(item, dict):
                            # Ensure item in list is not a dict or handle accordingly
                            item = frappe.utils.json.dumps(item)  # Convert dict to JSON string
                        child_entries.append({
                            "doctype": child_table_name,
                            "parentfield": field_name,  # Link field for child table
                            "value": item  # Store list item as 'value'
                        })
                    doc.set(field_name, child_entries)
            elif isinstance(value, dict):
                # Flatten the dictionary or convert it to a JSON string
                json_value = frappe.utils.json.dumps(value)  # Convert to JSON string
                doc.set(field_name, json_value)  # Set the JSON string as the field value
            else:
                # Set the simple value directly
                doc.set(field_name, value)

        # Insert the new document
        try:
            doc.insert()
        except Exception as e:
            frappe.throw(f"Error inserting document: {str(e)}")

def prepare_chart_data(products):
    """
    Prepare the data for bar chart generation.
    """
    # Example: Prepare bar chart data for product prices vs. titles
    labels = [product['title'] for product in products]  # Product titles as labels
    data_points = [product['price'] for product in products]  # Product prices as data points

    chart_data = {
        "labels": labels,
        "datasets": [{
            "label": "Product Prices",
            "data": data_points
        }]
    }

    return chart_data

@frappe.whitelist(allow_guest=True)
def get_table_data(table_name=None, file_upload=False):
    if table_name:
        import json
        if json.loads(file_upload.lower()):
            frappe.log_error("file_upload",type(json.loads(file_upload.lower())))
            return convert_uploaded_data_to_chart_dataset(table_name)
        else:
            data=frappe.db.get_all(table_name,fields=['*'])
            return convert_dynamic_json_to_chart_dataset(data)



import re
import frappe

def sanitize_column_name(column_name):
    """Sanitize column names to be SQL-compliant."""
    column_name = re.sub(r'[\s\.]', '_', column_name)  # Replace spaces and dots with underscores

    if column_name[0].isdigit():  # If column starts with a number, prefix it
        column_name = "_" + column_name

    return column_name

def table_exists(table_name):
    """Check if a table already exists in the database."""
    existing_tables = frappe.db.sql(f"SHOW TABLES LIKE 'tab{table_name}'", as_dict=False)
    return bool(existing_tables)

@frappe.whitelist()
def create_table_from_insights_data(source_name, table_name):
    data_source = frappe.get_doc("Insights Data Source", source_name)
    columns = data_source.get_table_columns(table_name)

    # Sanitize column names
    column_name_mapping = {col["column"]: sanitize_column_name(col["column"]) for col in columns}
    column_names = list(column_name_mapping.values())

    frappe.log_error("Column Names", column_names)

    if not table_exists(table_name):
        # Commit any pending transactions before executing DDL
        frappe.db.commit()

        # Define column types (assuming all are VARCHAR for now; modify as needed)
        column_definitions = ", ".join([f"`{col}` VARCHAR(255)" for col in column_names])

        # Create table if it doesn't exist
        create_table_query = f"""
        CREATE TABLE `tab{table_name}` (
            id INT AUTO_INCREMENT PRIMARY KEY,
            {column_definitions}
        )
        """
        frappe.db.sql(create_table_query)
        frappe.db.commit()  # Explicit commit after table creation
        frappe.log_error("Table Created", f"{table_name} has been created.")
    else:
        frappe.log_error("Table Exists", f"{table_name} already exists, skipping creation.")

    # Fetch data from the source
    preview = data_source.get_table_preview(table_name)
    data = preview.get("data", [])  # Ensure we get a list

    frappe.log_error("Data", data)
    frappe.log_error("Column", column_names)

    if data and isinstance(data[0], list):
        formatted_columns = ", ".join([f"`{col}`" for col in column_names])
        placeholders = ", ".join(["%s"] * len(column_names))
        
        frappe.log_error("Formatted Columns", formatted_columns)
        frappe.log_error("Placeholders", placeholders)

        insert_query = f"INSERT INTO `tab{table_name}` ({formatted_columns}) VALUES ({placeholders})"
        frappe.log_error("Insert Query", insert_query)

        for row in data:
            row_values = list(row)  # Ensure correct row format
            frappe.db.sql(insert_query, tuple(row_values))

        frappe.db.commit()  # Commit inserted rows

    return {"message": f"Table `tab{table_name}` processed. {len(data)} rows inserted successfully!"}





def convert_uploaded_data_to_chart_dataset(table_name):
    data_source = frappe.get_doc("Insights Data Source", "File Uploads")
    preview = data_source.get_table_preview(table_name)
    create_table_from_insights_data("File Uploads", table_name)
    frappe.log_error("convert_uploaded_data_to_chart_datase",preview)
    if not preview or not isinstance(preview, dict) or 'data' not in preview:
        print("Invalid or empty preview data.")
        return {"labels": [], "datasets": []}
    
    data_rows = preview['data']
    if not data_rows or len(data_rows) < 2:  # Need at least headers + one data row
        print("Not enough data rows in preview.")
        return {"labels": [], "datasets": []}
    
    # First row contains column headers
    headers = data_rows[0]
    
    # Find suitable label and value fields
    label_field_index = None
    value_field_index = None
    
    # Try to identify appropriate fields - prefer string for label and number for value
    for i, header in enumerate(headers):
        # Check first data row to determine type
        if len(data_rows) > 1:
            value = data_rows[1][i]
            
            # If label field not found and this looks like a string
            if label_field_index is None and isinstance(value, str) and not value.isdigit():
                label_field_index = i
                
            # If value field not found and this looks like a number
            if value_field_index is None and (isinstance(value, (int, float)) or 
                                             (isinstance(value, str) and value.isdigit())):
                value_field_index = i
                
        if label_field_index is not None and value_field_index is not None:
            break
    
    # If we couldn't find appropriate fields, use first column as label and second as value
    if label_field_index is None:
        label_field_index = 0
    if value_field_index is None:
        # Try to find the first numeric column after the label column
        for i in range(len(headers)):
            if i != label_field_index and i < len(data_rows[1]):
                try:
                    float(data_rows[1][i])
                    value_field_index = i
                    break
                except (ValueError, TypeError):
                    pass
        
        # If still no value field, just use the next available column
        if value_field_index is None:
            value_field_index = 1 if label_field_index != 1 else 2
            if value_field_index >= len(headers):
                value_field_index = 0 if label_field_index != 0 else 1
    
    # Extract labels and values from the data rows (skipping the header row)
    labels = []
    values = []
    
    for row in data_rows[1:]:  # Skip headers
        if len(row) > max(label_field_index, value_field_index):
            labels.append(str(row[label_field_index]))
            try:
                values.append(float(row[value_field_index]))
            except (ValueError, TypeError):
                values.append(0)  # Default to 0 for non-numeric values
    
    # Build the chart dataset
    chart_dataset = {
        "labels": labels,
        "datasets": [
            {
                "name": headers[value_field_index],
                "values": values,
            }
        ]
    }
    return chart_dataset


def convert_dynamic_json_to_chart_dataset(json_data):
    """
    Convert a dynamic list of JSON data into a chart-compatible dataset,
    excluding specific fields from being used as labels or values.

    Args:
        json_data (list): A list of dictionaries containing the JSON data.

    Returns:
        dict: A dictionary containing labels and datasets for the chart.
    """
    if not json_data or not isinstance(json_data, list):
        print("Invalid or empty JSON data.")
        return {"labels": [], "datasets": []}  # Return empty dataset for invalid input

    # Fields to exclude
    excluded_fields = {
        "name", "creation", "modified", "modified_by", "owner",
        "docstatus", "idx"
    }

    # Identify label and value fields dynamically
    sample = json_data[0]  # Take the first record as a sample
    label_field = None
    value_field = None

    for key, value in sample.items():
        # Skip excluded fields and fields starting with an underscore
        if key in excluded_fields or key.startswith("_"):
            frappe.log_error("key",key)
            continue

        # frappe.log_error("key1",key)

        if label_field is None and isinstance(value, (str, int, float)):
            label_field = key  # First non-excluded string or identifier-like field
            frappe.log_error("label_field",label_field)
        elif value_field is None and isinstance(value, (int, float)):
            value_field = key  # First non-excluded numeric field
            frappe.log_error("value_field",value_field)
        if label_field and value_field:
            break  # Stop when both fields are found
        
    # Debug: Print the selected fields
    frappe.log_error("s1",f"Label Field: {label_field}, Value Field: {value_field}")

    # Fallback if no suitable fields are found
    if not label_field or not value_field:
        frappe.log_error("s2","No suitable fields found for labels or values.")
        return {"labels": [], "datasets": []}

    # Extract labels and values from the JSON data
    labels = [str(item.get(label_field, "")) for item in json_data]
    values = [float(item.get(value_field, 0)) for item in json_data]

    # Debug: Print extracted labels and values
    frappe.log_error("s3",f"Labels: {labels}")
    frappe.log_error("s4",f"Values: {values}")

    # Build the chart dataset
    chart_dataset = {
        "labels": labels,
        "datasets": [
            {
                "name": value_field,  # Use the value field as the dataset name
                "values": values,    # Values for the chart
            }
        ]
    }

    return chart_dataset
