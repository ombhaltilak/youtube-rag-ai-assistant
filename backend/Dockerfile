# Use an official lightweight Python image
FROM python:3.10-slim

# Install system dependencies required for FAISS (vector search) and building C++ extensions
RUN apt-get update && apt-get install -y \
    libgomp1 \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Create a non-root user with UID 1000 to comply with Hugging Face Spaces security standards
RUN useradd -m -u 1000 user

# Configure environment variables for local binaries and model caching
ENV PATH="/home/user/.local/bin:${PATH}"
ENV HF_HOME="/home/user/.cache/huggingface"
ENV FLASHRANK_CACHE="/home/user/.cache/flashrank"

# Initialize the application directory and set proper ownership for the non-root user
RUN mkdir -p /app && chown -R user:user /app
WORKDIR /app

# Switch context to the non-root user for security
USER user

# Copy the dependency list and install Python packages
COPY --chown=user:user requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application source code into the container
COPY --chown=user:user . .

# Ensure necessary text files exist and have the correct write permissions
RUN touch content.txt cleaned_content.txt

# Expose the default port used by Hugging Face Spaces
EXPOSE 7860

# Launch the application using Gunicorn for production-grade performance
# --timeout 120 is used to allow for heavy model loading or data processing tasks
# Ensure "server:app" matches your filename (e.g., app:app if your file is app.py)
CMD ["gunicorn", "--bind", "0.0.0.0:7860", "--timeout", "120", "--workers", "2", "server:app"]