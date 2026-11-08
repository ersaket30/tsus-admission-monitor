# TSUS Hyderabad 2027–28 PP2 admissions monitor

This repository checks the TSUS homepage and the known ShriPortal application form.
It sends one Gmail alert only when the portal visibly confirms **Academic Year 2027–28**
and the Board dropdown contains **Badhte Kadam (PP2)**.

The monitor does not submit an application or enter personal information.

## Configure GitHub

1. Create a **private** GitHub repository, for example `tsus-admission-monitor`.
2. Upload these files, preserving the `.github/workflows/monitor.yml` path.
3. In the repository, open **Settings → Secrets and variables → Actions → New repository secret**.
4. Add these secrets:
   - `GMAIL_SENDER` = `er.saket30@gmail.com`
   - `GMAIL_RECIPIENT` = `er.saket30@gmail.com`
   - `GMAIL_APP_PASSWORD` = your Google App Password (not your normal Gmail password).
5. Open **Settings → Actions → General → Workflow permissions**. Allow read and write permissions
   for repository contents, if the repository setting requires it.
6. Open the **Actions** tab, select **TSUS PP2 Admissions Watch**, and click **Run workflow**
   to test it. The workflow also runs hourly automatically.

## Important notes

- The script performs one check per workflow run. GitHub Actions starts the next run.
- The workflow stores `tsus_pp2_alert_sent.txt` in the repository after sending the alert,
  preventing repeated emails for the same opening.
- If the school changes the portal layout or uses a custom dropdown, the check may need
  adjustment. Review the Actions run log if a check fails.
- GitHub scheduled workflows can be delayed. Hourly scheduling is used as a practical
  starting point for a private repository's free Actions allowance.
- Never put your Gmail App Password in the Python file or commit it to the repository.
