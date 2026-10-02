import os
import glob
import pandas as pd

dataset_dir = "CICIOT23"
train_files = glob.glob(os.path.join(dataset_dir, "train", "*.csv"))

print("Loading dataset information...")
# Loading the same 3% sample you use in your training script
df_list = [pd.read_csv(f).sample(frac=0.03, random_state=42) for f in train_files]
df = pd.concat(df_list, ignore_index=True)

print("\n--- Dataset Shape ---")
print(f"Total Rows: {df.shape[0]}")
print(f"Total Columns: {df.shape[1]}")

print("\n--- Rows Per Class (Original Labels) ---")
print(df['label'].value_counts())