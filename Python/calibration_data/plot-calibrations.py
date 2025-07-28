import os
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np

# --- Configuration ---
CALIBRATION_FOLDER = "calibration_data"
G_TO_N_CONVERSION = 9.81 / 1000.0  # Conversion factor from grams to Newtons

# --- Helper Function to Find the Latest File ---
def find_latest_file(folder, prefix):
    """
    Finds the most recently modified file in a folder with a given prefix.
    
    Args:
        folder (str): The path to the directory to search.
        prefix (str): The prefix of the filenames to look for (e.g., "SML").
        
    Returns:
        str: The full path to the most recent file, or None if no matching file is found.
    """
    if not os.path.isdir(folder):
        print(f"Error: Calibration folder '{folder}' not found.")
        return None
        
    try:
        # Filter files by prefix and get their full paths and modification times
        files = [
            (os.path.join(folder, f), os.path.getmtime(os.path.join(folder, f)))
            for f in os.listdir(folder) if f.startswith(prefix) and f.endswith(".csv")
        ]
        
        if not files:
            print(f"Info: No calibration files found with prefix '{prefix}'.")
            return None
            
        # Sort files by modification time (most recent first) and return the path
        latest_file = max(files, key=lambda item: item[1])[0]
        print(f"Found latest '{prefix}' file: {os.path.basename(latest_file)}")
        return latest_file
        
    except Exception as e:
        print(f"An error occurred while searching for files: {e}")
        return None

# --- Main Plotting Logic ---
def plot_calibration_data():
    """
    Finds the latest SML and ATI calibration files, processes them,
    and plots the results on a single graph.
    """
    # Find the latest calibration files
    sml_file = find_latest_file(CALIBRATION_FOLDER, "SML")
    ati_file = find_latest_file(CALIBRATION_FOLDER, "ATI")

    if not sml_file and not ati_file:
        print("No calibration files found to plot.")
        return

    # Create a plot
    plt.style.use('seaborn-v0_8-whitegrid')
    fig, ax = plt.subplots(figsize=(12, 8))

    # --- Process and Plot SML Data ---
    if sml_file:
        try:
            df_sml = pd.read_csv(sml_file)
            # Convert grams to Newtons
            df_sml['Force_N'] = df_sml['Weight_g'] * G_TO_N_CONVERSION
            
            # Plot SML data
            ax.plot(df_sml['Force_N'], df_sml['SML_ADC_Raw'], 'o-', label='SML Raw ADC', color='red', linewidth=2)
            
            # Perform linear regression to show the trendline
            coeffs_sml = np.polyfit(df_sml['Force_N'], df_sml['SML_ADC_Raw'], 1)
            poly_sml = np.poly1d(coeffs_sml)
            ax.plot(df_sml['Force_N'], poly_sml(df_sml['Force_N']), '--', color='darkred', label=f'SML Fit (Slope: {coeffs_sml[0]:.2f})')

        except Exception as e:
            print(f"Error processing SML file '{sml_file}': {e}")

    # --- Process and Plot ATI Data ---
    if ati_file:
        try:
            df_ati = pd.read_csv(ati_file)
            # Convert grams to Newtons
            df_ati['Force_N'] = df_ati['Weight_g'] * G_TO_N_CONVERSION
            
            # Find all voltage columns
            voltage_columns = [col for col in df_ati.columns if col.startswith('ATI_V')]
            
            # Plot each ATI voltage channel
            for i, col in enumerate(voltage_columns):
                ax.plot(df_ati['Force_N'], df_ati[col], 's--', label=f'ATI Channel {i}', alpha=0.7)

        except Exception as e:
            print(f"Error processing ATI file '{ati_file}': {e}")

    # --- Final Plot Formatting ---
    ax.set_title('Sensor Calibration Data', fontsize=16, fontweight='bold')
    ax.set_xlabel('Applied Force (Newtons)', fontsize=12)
    ax.set_ylabel('Sensor Output (Raw ADC or Volts)', fontsize=12)
    ax.legend(loc='best', fontsize=10)
    ax.grid(True, which='both', linestyle='--', linewidth=0.5)
    
    plt.tight_layout()
    plt.show()


# --- Run the Script ---
if __name__ == "__main__":
    plot_calibration_data()
