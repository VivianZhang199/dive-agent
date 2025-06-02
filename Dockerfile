FROM public.ecr.aws/lambda/python:3.10

# Install OpenCV dependencies
RUN yum install -y gcc cmake make git wget unzip libjpeg-turbo-devel \
    && pip install --upgrade pip

# Install Python dependencies
COPY requirements.txt ./
RUN pip install -r requirements.txt

# Copy only your source code (not venv, .DS_Store, etc.)
COPY src/ ${LAMBDA_TASK_ROOT}/

# Command to run Lambda function (note the src. prefix)
CMD ["handler.lambda_handler"]