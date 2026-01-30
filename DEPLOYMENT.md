# AWS Deployment Guide

This guide will help you deploy the AI Reply Agent to an AWS EC2 instance.

## Prerequisites
- An AWS Account
- A terminal (Command Prompt, PowerShell, or Terminal)

## Step 1: Launch an EC2 Instance
1.  Log in to the [AWS Console](https://console.aws.amazon.com/).
2.  Go to **EC2** -> **Instances** -> **Launch Instances**.
3.  **Name**: `AI-Reply-Agent`
4.  **OS Image**: Select **Ubuntu** (Ubuntu Server 22.04 LTS is recommended).
5.  **Instance Type**: `t2.micro` (Free Tier eligible) or `t3.micro`.
6.  **Key Pair**: Create a new key pair (e.g., `aireply-key`). **Download the .pem file** and keep it safe.
7.  **Network Settings**:
    - Check **Allow SSH traffic from** -> **My IP**.
    - Check **Allow HTTP traffic from the internet**.
    - Check **Allow HTTPS traffic from the internet**.
8.  Click **Launch Instance**.

## Step 2: Configure Security Group
1.  Go to your instance in the AWS Console.
2.  Click the **Security** tab -> Click the **Security Group** link.
3.  Click **Edit inbound rules**.
4.  Add a new rule:
    - **Type**: Custom TCP
    - **Port range**: `8000`
    - **Source**: `0.0.0.0/0` (Anywhere) - *This allows you to access the dashboard.*
5.  Click **Save rules**.

## Step 3: Connect to the Server
1.  Open your terminal.
2.  Navigate to where you saved your `.pem` key.
3.  Connect via SSH (replace `your-key.pem` and `your-instance-ip`):
    ```bash
    ssh -i "your-key.pem" ubuntu@your-instance-ip
    ```
    *(Note: On Windows, you might need to use Putty or just PowerShell if OpenSSH is installed)*

## Step 4: Install Docker on the Server
Run this single command to install Docker automatically:

```bash
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
```

After it finishes, add your user to the docker group:
```bash
sudo usermod -aG docker $USER
```

**IMPORTANT**: Type `exit` to disconnect, then SSH back in for the changes to take effect.

## Step 5: Deploy the App
1.  **Transfer Files**: You need to copy your project files to the server. You can use `scp` from your local machine:
    ```bash
    # Run this from your local project folder
    scp -i "path/to/key.pem" -r . ubuntu@your-instance-ip:~/app
    ```
    *Alternatively, you can `git clone` your repo if you push it to GitHub.*

2.  **Start the App**:
    SSH back into the server and run:
    ```bash
    cd app
    docker compose up -d --build
    ```

## Step 6: Access the Dashboard
Open your browser and go to:
`http://your-instance-ip:8000`

Your app is now running 24/7!

## Maintenance
- **View Logs**: `docker compose logs -f`
- **Stop App**: `docker compose down`
- **Update App**:
    1. Upload new files.
    2. Run `docker compose up -d --build`
