# API Key Setup Guide

## eBird Status and Trends API Key

This project uses the eBird Status and Trends API to download bird abundance data. The API requires an access key from Cornell Lab of Ornithology.

### Security Notice

**IMPORTANT**: Never commit API keys to version control. The `.gitignore` file is configured to exclude `.env` files and other sensitive data.

### Setup Instructions

1. **Request an API Key**
   - Visit the eBird Status and Trends website
   - Request access from Cornell Lab of Ornithology
   - You'll receive a key like: `abc123def456`

2. **Store the Key Securely**

   There are two options:

   **Option A: Use the .env file (Recommended for this project)**
   - The `.env` file in the root directory stores the key
   - Format: `EBIRDST_KEY=your_actual_key_here`
   - This file is automatically ignored by git

   **Option B: Use R's .Renviron file (For R users)**
   - Add to `~/.Renviron` in your home directory:
     ```
     EBIRDST_KEY=your_actual_key_here
     ```
   - Restart R after editing
   - This makes the key available to all R sessions

3. **For R Scripts**
   - The key is accessed via `Sys.getenv("EBIRDST_KEY")`
   - The setup script (`code/ebirdst/R_setup_files/setup.R`) will verify the key is set
   - If using .env file, you may need to load it manually or copy to .Renviron

4. **For Python Scripts**
   - Install python-dotenv: `pip install python-dotenv`
   - Load the .env file:
     ```python
     from dotenv import load_dotenv
     import os

     load_dotenv()
     api_key = os.getenv('EBIRDST_KEY')
     ```

### Verification

To verify your key is properly set:

**In R:**
```r
key <- Sys.getenv("EBIRDST_KEY")
if (nchar(key) > 0) {
  cat("Key is set, length:", nchar(key), "\n")
} else {
  cat("Key is NOT set\n")
}
```

**In Python:**
```python
import os
from dotenv import load_dotenv

load_dotenv()
key = os.getenv('EBIRDST_KEY')
if key:
    print(f"Key is set, length: {len(key)}")
else:
    print("Key is NOT set")
```

### Troubleshooting

- If the key isn't working, verify it's exactly as provided (no extra spaces)
- R users: Remember to restart R after editing .Renviron
- Python users: Ensure .env file is in the project root or specify the path
- Check that the .env file is not accidentally committed to git

### Security Best Practices

1. Never hardcode keys in source files
2. Don't share your key with others
3. Regenerate the key if it's accidentally exposed
4. Use environment variables or secure key management systems
5. Keep .env files out of version control (already configured in .gitignore)