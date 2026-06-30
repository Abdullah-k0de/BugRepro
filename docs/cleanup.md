# Google Cloud & Firebase Cleanup Guide: BugRepro Sentinel

This guide provides instructions on how to stop, delete, and clean up all the deployed cloud resources to avoid incurring any ongoing GCP charges.

---

## 🖥️ 1. Delete Compute Engine VM Instance

This removes the VM server and stops the backend API container.

* **GCP Console Method**:
  1. Go to **Compute Engine > VM instances** in the GCP Console.
  2. Select the checkbox next to **`bugrepro-backend-vm`**.
  3. Click **Delete** at the top of the page.
* **CLI Command Method**:
  ```bash
  gcloud compute instances delete bugrepro-backend-vm --zone=us-central1-a --quiet
  ```

---

## 🔒 2. Delete Firewall Rules

This removes the public access ports we opened for the backend.

* **GCP Console Method**:
  1. Go to **VPC Network > Firewall** in the GCP Console.
  2. Select the checkbox next to **`allow-sentinel-port`** and **`allow-http-https`**.
  3. Click **Delete** at the top of the page.
* **CLI Command Method**:
  ```bash
  gcloud compute firewall-rules delete allow-sentinel-port allow-http-https --quiet
  ```

---

## 📦 3. Delete Artifact Registry Repository

This deletes the Docker container images we built and stored.

* **GCP Console Method**:
  1. Go to **Artifact Registry > Repositories** in the GCP Console.
  2. Select the checkbox next to **`repro-registry`**.
  3. Click **Delete** at the top of the page.
* **CLI Command Method**:
  ```bash
  gcloud artifacts repositories delete repro-registry --location=us-central1 --quiet
  ```

---

## 🔑 4. Remove Vertex AI IAM Policy Binding (Optional)

This revokes the model execution permission from the GCE default service account.

* **GCP Console Method**:
  1. Go to **IAM & Admin > IAM** in the GCP Console.
  2. Locate the Compute Engine default service account: `YOUR_PROJECT_NUMBER-compute@developer.gserviceaccount.com`.
  3. Click the **Edit Pencil Icon** next to it.
  4. Find the **Vertex AI User** role card and click the **Trash/Remove Icon**.
  5. Click **Save**.
* **CLI Command Method**:
  ```bash
  gcloud projects remove-iam-policy-binding YOUR_PROJECT_ID --member="serviceAccount:YOUR_PROJECT_NUMBER-compute@developer.gserviceaccount.com" --role="roles/aiplatform.user"
  ```

---

## 🌐 5. Disable Firebase Hosting (Frontend)

This disables the live public website and stops serving the web client.

* **Firebase Console Method**:
  1. Open the [Firebase Console](https://console.firebase.google.com/) and select project **`bug-repro-17eb1`**.
  2. Go to **Build > Hosting** in the left sidebar.
  3. Under the **Release History** section, click the three dots (`...`) next to the active version.
  4. Click **Disable Hosting**.
* **CLI Command Method** (Run from `bugrepro-frontend` directory):
  ```bash
  firebase hosting:disable
  ```

---

## 🧹 6. VM Disk Maintenance & Garbage Collection (Ongoing)

If you are **not** destroying the VM but want to ensure it remains running healthy indefinitely without filling up its 10 GB disk, use the following manual and automatic garbage collection commands:

### Safe Manual Prune
Free up unused container instances, dangling build logs, and temporary virtual networks instantly:
```bash
# SSH into the VM host first
gcloud compute ssh bugrepro-backend-vm --zone=us-central1-a

# Run a safe prune
sudo docker system prune --volumes -f
```

### Nightly Cron Job Setup
Automate this prune to run every night at 3:00 AM:
1. Open the root crontab:
   ```bash
   sudo crontab -e
   ```
2. Add this line:
   ```bash
   0 3 * * * /usr/bin/docker system prune --volumes -f
   ```

> [!CAUTION]
> **NEVER run `docker system prune -a` in an automated cron job.**
> Doing so will delete all non-running Docker images. Since the compiler sandbox (`sentinel-sandbox:latest`) only launches on-demand when analyzing bugs, a cron job with `-a` will delete it. This forces the server to do a slow 5-minute sandbox compilation from scratch on the next user request!

