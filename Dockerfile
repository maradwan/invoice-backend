# Use official Python image
FROM python:3.10

# Install system dependencies (including zbar)
RUN apt-get update && apt-get install -y \
    poppler-utils \
    libzbar0 \
    && rm -rf /var/lib/apt/lists/*

# Set the working directory
WORKDIR /app/src

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the entire project
COPY . .

# Expose the FastAPI port
EXPOSE 8000

# Run FastAPI with the correct path
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
