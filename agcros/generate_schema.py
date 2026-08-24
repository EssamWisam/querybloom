import pandas as pd
import os
import yaml
from datetime import datetime


def get_column_info(df, col):
    """Extract comprehensive information for a single column."""
    total = len(df)
    non_null = df[col].notna().sum()
    null_count = total - non_null
    null_percentage = round((null_count / total * 100), 2) if total > 0 else 0

    col_info = {
        "name": col,
        "type": str(df[col].dtype),
        "non_null_count": int(non_null),
        "null_count": int(null_count),
        "null_percentage": float(null_percentage),
    }

    # Add unique count
    try:
        unique_count = df[col].nunique()
        col_info["unique_values"] = int(unique_count)
    except:
        pass

    # Add statistics for numeric columns
    if pd.api.types.is_numeric_dtype(df[col]):
        try:
            col_info["min"] = (
                float(df[col].min()) if not pd.isna(df[col].min()) else None
            )
            col_info["max"] = (
                float(df[col].max()) if not pd.isna(df[col].max()) else None
            )
            col_info["mean"] = (
                round(float(df[col].mean()), 2) if not pd.isna(df[col].mean()) else None
            )
        except:
            pass

    # Sample non-null values (up to 5)
    sample_values = df[col].dropna().head(5).tolist()
    if sample_values:
        # Convert to native Python types for YAML serialization
        col_info["sample_values"] = [
            str(v) if not isinstance(v, (int, float, str, bool)) else v
            for v in sample_values
        ]

    return col_info


def get_schema_info(df):
    """Extract comprehensive schema information from a DataFrame."""
    schema = []
    for col in df.columns:
        schema.append(get_column_info(df, col))
    return schema


def sort_sheet_names(sheet_names):
    """Sort sheet names: meta sheets first (alphabetically), then rest (alphabetically)."""
    meta_sheets = [name for name in sheet_names if "meta" in name.lower()]
    other_sheets = [name for name in sheet_names if "meta" not in name.lower()]

    meta_sheets.sort()
    other_sheets.sort()

    return meta_sheets + other_sheets


def format_schema_to_file(excel_path, output_file="agcros_schema.yaml"):
    """Generate a comprehensive schema file in YAML format for all sheets."""

    if not os.path.exists(excel_path):
        raise FileNotFoundError(f"Excel file not found: {excel_path}")

    # Read all sheets
    excel_file = pd.ExcelFile(excel_path)
    sheet_names = excel_file.sheet_names

    # Sort sheets: meta sheets first, then rest alphabetically
    sorted_sheet_names = sort_sheet_names(sheet_names)

    schema_dict = {
        "metadata": {
            "source_file": os.path.basename(excel_path),
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "total_sheets": len(sorted_sheet_names),
        },
        "sheets": [],
    }

    # Process each sheet
    for idx, sheet_name in enumerate(sorted_sheet_names, 1):
        print(f"Processing sheet {idx}/{len(sheet_names)}: {sheet_name}")

        df = pd.read_excel(excel_path, sheet_name=sheet_name)
        columns_info = get_schema_info(df)

        sheet_info = {
            "name": sheet_name,
            "row_count": int(df.shape[0]),
            "column_count": int(df.shape[1]),
            "columns": columns_info,
        }

        schema_dict["sheets"].append(sheet_info)

    # Write to YAML file
    with open(output_file, "w", encoding="utf-8") as f:
        yaml.dump(
            schema_dict,
            f,
            default_flow_style=False,
            sort_keys=False,
            allow_unicode=True,
            width=120,
        )

    print(f"\n✓ Schema file generated: {output_file}")


def format_highlevel_schema_to_file(
    excel_path, output_file="agcros_schema_highlevel.yaml"
):
    """Generate a high-level schema file with just column names, marking 100% null columns."""

    if not os.path.exists(excel_path):
        raise FileNotFoundError(f"Excel file not found: {excel_path}")

    # Read all sheets
    excel_file = pd.ExcelFile(excel_path)
    sheet_names = excel_file.sheet_names

    # Sort sheets: meta sheets first, then rest alphabetically
    sorted_sheet_names = sort_sheet_names(sheet_names)

    schema_dict = {
        "metadata": {
            "source_file": os.path.basename(excel_path),
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "total_sheets": len(sorted_sheet_names),
            "note": "Columns marked with * have 100% null values",
        },
        "sheets": [],
    }

    # Process each sheet
    for idx, sheet_name in enumerate(sorted_sheet_names, 1):
        print(f"Processing sheet {idx}/{len(sheet_names)}: {sheet_name}")

        df = pd.read_excel(excel_path, sheet_name=sheet_name)

        # Get column names and mark 100% null columns
        columns = []
        for col in df.columns:
            total = len(df)
            null_count = total - df[col].notna().sum()
            is_all_null = (null_count == total) if total > 0 else False

            column_name = f"{col} *" if is_all_null else col
            columns.append(column_name)

        sheet_info = {
            "name": sheet_name,
            "row_count": int(df.shape[0]),
            "column_count": int(df.shape[1]),
            "columns": columns,
        }

        schema_dict["sheets"].append(sheet_info)

    # Write to YAML file
    with open(output_file, "w", encoding="utf-8") as f:
        yaml.dump(
            schema_dict,
            f,
            default_flow_style=False,
            sort_keys=False,
            allow_unicode=True,
            width=120,
        )

    print(f"\n✓ High-level schema file generated: {output_file}")


if __name__ == "__main__":
    excel_path = "AgCros.xlsx"
    output_file = "agcros_schema.yaml"
    output_file_highlevel = "agcros_schema_highlevel.yaml"

    print("=" * 100)
    print("Generating YAML Schema Files...")
    print("=" * 100)

    # Generate comprehensive schema
    print("\n[1/2] Generating comprehensive schema...")
    format_schema_to_file(excel_path, output_file)

    # Generate high-level schema
    print("\n[2/2] Generating high-level schema...")
    format_highlevel_schema_to_file(excel_path, output_file_highlevel)

    print("\n" + "=" * 100)
    print(f"✓ Comprehensive schema: {output_file}")
    print(f"✓ High-level schema: {output_file_highlevel}")
    print("=" * 100)
