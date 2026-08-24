import pandas as pd
import os


def convert_excel_to_dataframes(excel_path):
    """
    Convert an Excel file with multiple sheets into multiple DataFrames.

    Args:
        excel_path: Path to the Excel file

    Returns:
        dict: Dictionary where keys are sheet names and values are DataFrames
    """
    if not os.path.exists(excel_path):
        raise FileNotFoundError(f"Excel file not found: {excel_path}")

    # Read all sheets from the Excel file
    excel_file = pd.ExcelFile(excel_path)

    # Get all sheet names
    sheet_names = excel_file.sheet_names
    print(f"Found {len(sheet_names)} sheets in the Excel file:")
    for i, name in enumerate(sheet_names, 1):
        print(f"  {i}. {name}")
    print()

    # Create a dictionary to store all dataframes
    dataframes = {}

    # Read each sheet into a dataframe
    for sheet_name in sheet_names:
        df = pd.read_excel(excel_path, sheet_name=sheet_name)
        dataframes[sheet_name] = df
        print(f"Sheet '{sheet_name}': {df.shape[0]} rows × {df.shape[1]} columns")

    return dataframes


def save_dataframes_to_csv(dataframes, output_dir="output_csvs"):
    """
    Save each dataframe to a separate CSV file.

    Args:
        dataframes: Dictionary of sheet_name -> DataFrame
        output_dir: Directory to save CSV files
    """
    os.makedirs(output_dir, exist_ok=True)

    for sheet_name, df in dataframes.items():
        # Clean the sheet name for use as filename
        filename = f"{sheet_name.replace(' ', '_').replace('/', '_')}.csv"
        output_path = os.path.join(output_dir, filename)
        df.to_csv(output_path, index=False)
        print(f"Saved '{sheet_name}' to {output_path}")


if __name__ == "__main__":
    # Path to the Excel file
    excel_path = "AgCros.xlsx"

    # Convert Excel to dataframes
    print("=" * 60)
    print("Converting Excel file to DataFrames...")
    print("=" * 60)
    dataframes = convert_excel_to_dataframes(excel_path)

    print("\n" + "=" * 60)
    print("DataFrames loaded successfully!")
    print("=" * 60)

    # Optional: Save to CSV files
    print("\n" + "=" * 60)
    print("Saving DataFrames to CSV files...")
    print("=" * 60)
    save_dataframes_to_csv(dataframes, output_dir="output_csvs")

    # Optional: Display first few rows of each dataframe
    print("\n" + "=" * 60)
    print("Preview of each sheet:")
    print("=" * 60)
    for sheet_name, df in dataframes.items():
        print(f"\n--- {sheet_name} ---")
        print(df.head(3))
        print()

    # You can now work with individual dataframes like:
    # df1 = dataframes['Sheet1']
    # df2 = dataframes['Sheet2']
    # etc.
