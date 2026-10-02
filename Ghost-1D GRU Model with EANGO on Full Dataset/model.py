import torch
import torch.nn as nn
import math

class GhostModule1D(nn.Module):
    def __init__(self, in_channels, out_channels, kernel_size=3, ratio=2, dw_size=3, stride=1, relu=True):
        super(GhostModule1D, self).__init__()
        self.out_channels = out_channels
        init_channels = math.ceil(out_channels / ratio)
        new_channels = init_channels * (ratio - 1)

        self.primary_conv = nn.Sequential(
            nn.Conv1d(in_channels, init_channels, kernel_size, stride, kernel_size // 2, bias=False),
            nn.BatchNorm1d(init_channels),
            nn.ReLU(inplace=True) if relu else nn.Sequential(),
        )

        self.cheap_operation = nn.Sequential(
            nn.Conv1d(init_channels, new_channels, dw_size, 1, dw_size // 2, groups=init_channels, bias=False),
            nn.BatchNorm1d(new_channels),
            nn.ReLU(inplace=True) if relu else nn.Sequential(),
        )

    def forward(self, x):
        x1 = self.primary_conv(x)
        x2 = self.cheap_operation(x1)
        out = torch.cat([x1, x2], dim=1)
        return out[:, :self.out_channels, :]

class Ghost1D_GRU(nn.Module):
    def __init__(self, input_dim=11, num_classes=5, hidden_gru=32):
        super(Ghost1D_GRU, self).__init__()
        
        self.ghost_block = nn.Sequential(
            GhostModule1D(in_channels=1, out_channels=16, kernel_size=3, ratio=2),
            nn.MaxPool1d(kernel_size=2, stride=1, padding=1),
            GhostModule1D(in_channels=16, out_channels=32, kernel_size=3, ratio=2),
            nn.MaxPool1d(kernel_size=2, stride=1, padding=1)
        )
        
        self.gru = nn.GRU(
            input_size=32,
            hidden_size=hidden_gru,
            num_layers=1,
            batch_first=True
        )
        
        # Adaptive pooling ensures fixed dimension regardless of sequence length
        self.global_pool = nn.AdaptiveAvgPool1d(1)
        
        self.classifier = nn.Sequential(
            nn.Linear(hidden_gru, 32),
            nn.ReLU(inplace=True),
            nn.Dropout(0.2),
            nn.Linear(32, num_classes)
        )

    def forward(self, x):
        x = x.unsqueeze(1)
        features = self.ghost_block(x)
        features = features.permute(0, 2, 1)
        gru_out, _ = self.gru(features)
        
        # Pool across sequence dimension: (batch, hidden_gru, 1) -> (batch, hidden_gru)
        pooled = self.global_pool(gru_out.permute(0, 2, 1)).squeeze(-1)
        logits = self.classifier(pooled)
        return logits

if __name__ == "__main__":
    model = Ghost1D_GRU(input_dim=11, num_classes=5)
    total_params = sum(p.numel() for p in model.parameters() if p.requires_grad)
    print(f"Model parameters: {total_params:,} (~{total_params * 4 / 1024:.2f} KB)")