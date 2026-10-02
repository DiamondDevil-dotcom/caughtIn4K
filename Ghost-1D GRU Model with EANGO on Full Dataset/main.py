import json
import os
import glob
import pandas as pd
import numpy as np
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score
from sklearn.preprocessing import LabelEncoder, StandardScaler
from EA_NGO import EANGO

dataset_dir = "CICIOT23"
train_files = glob.glob(os.path.join(dataset_dir, "train", "*.csv"))

print("Loading and sampling data...")
df_list = []
for file in train_files:
    df = pd.read_csv(file).sample(frac=0.01, random_state=42) 
    df_list.append(df)
    
df = pd.concat(df_list, ignore_index=True)

attack_mapping = {
    'DDoS-ICMP_Flood': 'DDoS', 'DDoS-UDP_Flood': 'DDoS', 'DDoS-TCP_Flood': 'DDoS',
    'DDoS-PSHACK_Flood': 'DDoS', 'DDoS-SYN_Flood': 'DDoS', 'DDoS-RSTFINFlood': 'DDoS',
    'DDoS-SynonymousIP_Flood': 'DDoS', 'DDoS-UDP_Fragmentation': 'DDoS', 'DDoS-ACK_Fragmentation': 'DDoS',
    'DDoS-ICMP_Fragmentation': 'DDoS',
    'DoS-UDP_Flood': 'DoS', 'DoS-TCP_Flood': 'DoS', 'DoS-SYN_Flood': 'DoS', 'DoS-HTTP_Flood': 'DoS',
    'Mirai-greeth_flood': 'Mirai', 'Mirai-udpplain': 'Mirai', 'Mirai-greip_flood': 'Mirai',
    'Recon-HostDiscovery': 'Recon', 'Recon-PortScan': 'Recon', 'Recon-OSScan': 'Recon',
    'BenignTraffic': 'Benign'
}

df['macro_label'] = df['label'].map(attack_mapping)
df = df.dropna(subset=['macro_label'])

X = df.drop(columns=['label', 'macro_label'])

# Remove infinite values
X = X.replace([np.inf, -np.inf], np.nan)
print(f"Columns before cleaning: {X.shape[1]}")

nan_cols = X.columns[X.isna().any()]

print(f"Columns with NaN: {len(nan_cols)}")

if len(nan_cols) > 0:
    print(list(nan_cols))

# Remove columns that are completely empty
X = X.dropna(axis=1, how="all")

# Fill remaining missing values
X = X.fillna(X.median(numeric_only=True))

# Remove constant columns (zero variance)
constant_cols = X.columns[X.nunique() <= 1]

if len(constant_cols) > 0:
    print(f"Removing {len(constant_cols)} constant columns:")
    print(list(constant_cols))
    X = X.drop(columns=constant_cols)

y = df['macro_label']

encoder = LabelEncoder()
y_encoded = encoder.fit_transform(y)

scaler = StandardScaler()
X_scaled = scaler.fit_transform(X)

print(f"Data ready. Shape: {X_scaled.shape}. Running EA-NGO Feature Selection...")
n_features = X_scaled.shape[1]

def fitness_function(solution):
    selected_features = solution > 0.5
    if np.sum(selected_features) == 0:
        return 1.0 
        
    X_subset = X_scaled[:, selected_features]
    X_tr, X_val, y_tr, y_val = train_test_split(X_subset, y_encoded, test_size=0.2, random_state=42)
    
    clf = RandomForestClassifier(n_estimators=10, max_depth=5, random_state=42, n_jobs=-1)
    clf.fit(X_tr, y_tr)
    preds = clf.predict(X_val)
    acc = accuracy_score(y_val, preds)
    
    error_rate = 1.0 - acc
    feature_ratio = np.sum(selected_features) / n_features
    
    # RELAXED PENALTY: Now prioritizes 99% accuracy and only 1% feature reduction
    loss = (0.99 * error_rate) + (0.01 * feature_ratio)
    return loss

optimizer = EANGO(
    obj_func=fitness_function,
    n_features=n_features,
    pop_size=30,
    max_iter=50,
    lb=0.0,
    ub=1.0,
    seed=42
)

best_position, best_fitness = optimizer.optimize()

optimal_features_mask = best_position.astype(bool)
selected_columns = X.columns[optimal_features_mask].tolist()

print(f"\n--- EA-NGO Optimization Complete ---")
print(f"Original Features: {n_features}")
print(f"Selected Features ({len(selected_columns)}):")
print(selected_columns)

# Save selected features
with open("selected_features.json", "w") as f:
    json.dump(selected_columns, f, indent=4)

print("\nSelected features saved to selected_features.json")