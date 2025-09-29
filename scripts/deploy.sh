#!/bin/bash
set -e # Exit immediately if a command exits with a non-zero status.

# --- Usage Function ---
usage() {
    echo "Usage: $0 [options]"
    echo "Options:"
    echo "  --resource-group <name>  Set the resource group name (default: rg-patient-outreach)"
    echo "  --location <region>      Set the Azure region (default: eastus2)"
    echo "  --plan <name>            Set the App Service Plan name (default: asp-patientoutreach)"
    echo "  --name <name>            Set the Web App name (default: patientoutreach-20250926)"
    echo "  --sku <sku>              Set the App Service Plan SKU (default: P1v3)"
    echo "  -h, --help               Display this help message"
}

# --- Default Configuration ---
RESOURCE_GROUP="rg-patient-outreach"
LOCATION="eastus2"
APP_SERVICE_PLAN="asp-patientoutreach"
WEB_APP_NAME="patientoutreach-20250926"
SKU="P1v3"
PYTHON_VERSION="3.12"

# --- Argument Parsing ---
while [[ "$#" -gt 0 ]]; do
    case $1 in
        --resource-group) RESOURCE_GROUP="$2"; shift ;;
        --location) LOCATION="$2"; shift ;;
        --plan) APP_SERVICE_PLAN="$2"; shift ;;
        --name) WEB_APP_NAME="$2"; shift ;;
        --sku) SKU="$2"; shift ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Unknown parameter passed: $1"; usage; exit 1 ;;
    esac
    shift
done

# --- Login and Subscription ---
echo "Step 1: Clearing local Azure credentials..."
az logout
echo "Step 2: Logging in to Azure..."
az login

echo "Step 3: Selecting Azure Subscription..."
az account list --output table
read -p "Enter the Subscription ID you want to use: " SUBSCRIPTION_ID
az account set --subscription "$SUBSCRIPTION_ID"
echo "Using subscription: $SUBSCRIPTION_ID"

# --- Resource Creation ---
echo "Step 4: Creating Resource Group '$RESOURCE_GROUP'..."
az group create --name "$RESOURCE_GROUP" --location "$LOCATION"

echo "Step 5: Creating App Service Plan '$APP_SERVICE_PLAN'..."
az appservice plan create --name "$APP_SERVICE_PLAN" --resource-group "$RESOURCE_GROUP" --location "$LOCATION" --sku "$SKU" --is-linux

echo "Step 6: Creating Web App '$WEB_APP_NAME' with Python $PYTHON_VERSION runtime..."
az webapp create --resource-group "$RESOURCE_GROUP" --plan "$APP_SERVICE_PLAN" --name "$WEB_APP_NAME" --runtime "PYTHON|$PYTHON_VERSION"

echo "Step 7: Configuring startup command for Gunicorn..."
STARTUP_COMMAND="gunicorn -w 4 -k uvicorn.workers.UvicornWorker app.main:app"
az webapp config set --resource-group "$RESOURCE_GROUP" --name "$WEB_APP_NAME" --startup-file "$STARTUP_COMMAND"

echo "Step 7.5: Forcing build-on-deploy to ensure packages are installed..."
az webapp config appsettings set --resource-group "$RESOURCE_GROUP" --name "$WEB_APP_NAME" --settings "SCM_DO_BUILD_DURING_DEPLOYMENT=true" "ENABLE_ORYX_BUILD=true"

echo "Waiting 15 seconds to let the SCM site restart..."
sleep 15

# --- Code Deployment ---
echo "Step 8: Preparing code for deployment..."
# Create a zip file using Python to ensure cross-platform compatibility and exclude __pycache__
echo "Creating deployment.zip..."
rm -f deployment.zip

python -c "import os, zipfile
with zipfile.ZipFile('deployment.zip', 'w', zipfile.ZIP_DEFLATED) as zf:
    zf.write('requirements.txt')
    for root, dirs, files in os.walk('app'):
        # Exclude __pycache__ directories from the zip
        if '__pycache__' in dirs:
            dirs.remove('__pycache__')
        for file in files:
            file_path = os.path.join(root, file)
            archive_name = os.path.relpath(file_path, os.path.join('app', '..'))
            zf.write(file_path, archive_name)
"

echo "Step 9: Deploying application code via zip push (config-zip)..."
az webapp deployment source config-zip --resource-group "$RESOURCE_GROUP" --name "$WEB_APP_NAME" --src deployment.zip
if [ $? -ne 0 ]; then
    echo "Error: Zip deployment failed." >&2
    rm deployment.zip
    exit 1
fi

# Clean up the zip file
rm deployment.zip

# --- App Settings Configuration ---
echo "Step 10: Configuring application settings from .env file..."

if [ -f ".env" ]; then
    echo "Found .env file. Generating JSON configuration to handle multi-line values..."
    
    # Use Python to parse the .env file and generate a JSON file.
    # This is the most robust way to handle multi-line strings and special characters.
    python -c "import os, json
from dotenv import dotenv_values

print('Generating appsettings.json...')
config = dotenv_values('.env')
app_settings = []
for key, value in config.items():
    if value is not None:
        app_settings.append({'name': key, 'value': value, 'slotSetting': False})

with open('appsettings.json', 'w', encoding='utf-8') as f:
    json.dump(app_settings, f, indent=2)
"
    
    if [ -f "appsettings.json" ]; then
        echo "Applying settings from appsettings.json in a single batch..."
        az webapp config appsettings set --resource-group "$RESOURCE_GROUP" --name "$WEB_APP_NAME" --settings "@appsettings.json"
        
        if [ $? -ne 0 ]; then
            echo "Error: Failed to set application settings from appsettings.json." >&2
            rm appsettings.json
            exit 1
        fi
        
        rm appsettings.json
        echo "Application settings from .env file configured successfully."
    else
        echo "Failed to generate appsettings.json."
    fi
else
    echo "Warning: .env file not found. Skipping automatic configuration of application settings."
fi

# --- Finalization ---
echo "Step 11: Setting dynamic application settings..."
WEB_APP_HOSTNAME=$(az webapp show --name "$WEB_APP_NAME" --resource-group "$RESOURCE_GROUP" --query "defaultHostName" --output tsv)
APP_URL="https://$WEB_APP_HOSTNAME"

echo "Setting APP_BASE_URL to the application's public URL: $APP_URL"
az webapp config appsettings set --resource-group "$RESOURCE_GROUP" --name "$WEB_APP_NAME" --settings "APP_BASE_URL=$APP_URL"

echo "----------------------------------------------------"
echo "Deployment Complete!"
echo "Your application is available at: $APP_URL"
echo ""
echo "Next Steps:"
echo "1. If you haven't already, go to the Azure Portal and navigate to the '$WEB_APP_NAME' App Service."
echo "2. Under 'Settings' -> 'Configuration', ensure all required settings like 'ACS_CONNECTION_STRING' are present and correct."
echo "3. The app will restart and use the new settings."
echo "----------------------------------------------------"
