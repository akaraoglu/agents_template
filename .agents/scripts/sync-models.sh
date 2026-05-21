#!/bin/bash

  # Path to the directory containing your model folders
  MODELS_DIR=".agents/models"

  # Check if the directory exists
  if [ ! -d "$MODELS_DIR" ]; then
      echo "Error: Directory $MODELS_DIR not found."
      exit 1
  fi

  echo "Checking for models to sync..."

  # Loop through each subdirectory in the models folder
  for folder in "$MODELS_DIR"/*/; do
      # Remove trailing slash from folder path
      folder=${folder%/}
      folder_name=$(basename "$folder")

      # --- OPTION 1: Extract Model Name from File ---
      # We check for a file named 'model_name' inside the folder.
      # If it doesn't exist, we fallback to the folder name.
      if [ -f "$folder/model_name" ]; then
          model_name=$(cat "$folder/model_name")
          echo "Found explicit name for $folder_name: $model_name"
      else
          model_name=$folder_name
          echo "Using folder name for $folder_name: $model_name"
      fi

      # Check if a Modelfile exists in the folder
      if [ ! -f "$folder/Modelfile" ]; then
          echo "Skipping $folder_name: No Modelfile found."
          continue
      fi

      # Check if the model is already installed in Ollama
      if ollama list | grep -q "$model_name"; then
          echo "Model '$model_name' is already installed. Skipping..."
      else
          echo "Installing model '$model_name' from $folder/Modelfile..."
          ollama create "$model_name" -f "$folder/Modelfile"

          if [ $? -eq 0 ]; then
              echo "Successfully installed $model_name."
          else
              echo "Failed to install $model_name."
          fi
      fi
  done

  echo "Sync complete!"

