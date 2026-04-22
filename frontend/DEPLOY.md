# Deployment Guide

## 1. Environment Variables
Create a `.env` file in the root of `frontend/packages/client`:

```bash
# Common
TARO_APP_API_BASE_URL=https://api.stockagent.com
TARO_APP_VERSION=1.0.0

# WeChat Mini Program
TARO_APP_WECHAT_APPID=wx1234567890abcdef

# H5
TARO_APP_H5_TITLE="Stock Agent"
```

## 2. Build & Deploy

### WeChat Mini Program
1.  Run build command:
    ```bash
    pnpm build:weapp
    ```
2.  Open **WeChat Developer Tools**.
3.  Import the directory: `frontend/packages/client/dist-weapp`.
4.  Click **Upload** to submit a review version.

### Web (H5)
1.  Run build command:
    ```bash
    pnpm build:h5
    ```
2.  Output directory: `frontend/packages/client/dist-h5`.
3.  Deploy to Vercel:
    *   Root Directory: `frontend`
    *   Build Command: `pnpm -F client build:h5`
    *   Output Directory: `packages/client/dist-h5`

## 3. CI/CD Secrets
Configure the following secrets in GitHub Repository Settings:

*   `WECHAT_APP_ID`: Your WeChat App ID
*   `WECHAT_MINI_PRIVATE_KEY`: Private key for CI upload
*   `SERVER_SSH_KEY`: SSH Key for backend deployment

## 4. Rollback Strategy
*   **Frontend**: Revert Git commit and re-trigger GitHub Actions.
*   **Backend**: Use Kubernetes `rollout undo` command:
    ```bash
    kubectl rollout undo deployment/java-backend
    ```
