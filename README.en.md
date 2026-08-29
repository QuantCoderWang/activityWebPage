# Activity Coupon Grabbing Platform (Web)

_A standalone Web marketing activity platform, independent of the mini-program mall_

![Python](https://img.shields.io/badge/Python-3.12%2B-blue)
![Flask](https://img.shields.io/badge/Flask-3.0.3-green)
![License](https://img.shields.io/badge/License-MIT-yellow)

</div>

---

## 📖 Introduction

**CheHengMei Activity Coupon Grabbing Platform** is a standalone Web marketing activity site built alongside the existing mini-program mall, featuring the "Shake to Grab Coupons" gameplay.

Users participate in the lottery directly through activity links. After winning, coupons are automatically issued to their mall accounts via an SM4 national cryptographic encrypted channel; unregistered users are guided to scan a QR code and register in the mini-program, continuously driving traffic to the mall.

### Project Highlights

- ⚡ **Quick Campaign Launch**: Configure an activity in the admin panel within minutes and generate a dedicated link for instant distribution to WeChat Moments, official accounts, and communities
- 🎲 **Flexible Gameplay**: Multi-tier prizes + probability-based lottery + non-winning fallback, with support for dynamically adjusting odds and stock during an active campaign
- 🔐 **Secure Integration**: Mobile numbers encrypted with SM4 national cryptography, automatic rollback on coupon issuance failures, dual validation on both frontend and backend
- 🚀 **Concurrency Safety**: Process locks prevent stock overselling, draw and win limits prevent coupon farming

## ✨ Features Overview

### User Side

| Feature | Description |
|---|---|
| Activity Display | Rich-text introduction, real-time updates of remaining/total prize stock |
| Shake to Draw | Animation feedback + result pop-up, mobile number remembered locally to avoid re-entry |
| Auto Coupon Issuance | Coupons matched by mobile number upon winning, delivered directly to the mall account |
| Registration Guide | Unregistered users see a guidance section with the mini-program QR code |
| Activity Ending | All entries automatically collapse when prizes run out, showing only the ending notice |

### Admin Dashboard

| Feature | Description |
|---|---|
| Activity Management | Create/configure activity codes, names, multi-slot open hours, per-user draw limits |
| Rich Text Editing | wangEditor rich text editor with image upload support, editable anytime |
| Prize Configuration | Pull coupon names from the remote coupon library, configure rank/odds/stock, automatic total-probability validation |
| Data Statistics | Draw record details, participant count (deduplicated), winning statistics |
| Live Adjustment | Stock (not below already issued), odds, and rich text can be modified mid-campaign, taking effect immediately upon saving |

## 🏗️ Architecture

**Tech Stack**

| Layer | Technology |
|---|---|
| Backend Framework | Python Flask + Flask-SQLAlchemy |
| Database | SQLite (activity data) + PyMySQL / mysql-connector-python (remote mall database) |
| Security | cryptography (SM4 national cryptographic encryption for mobile numbers) |
| Frontend | Jinja2 templates + Vanilla JavaScript + wangEditor |
| Deployment | Gunicorn (can be paired with Nginx reverse proxy in production) |

## 📦 Installation Guide

### Requirements

- Python 3.12+
- An accessible remote mall database (for registration verification and coupon issuance)

### Steps
bash

1. Clone the repository
git clone https://gitee.com/your_username/project_name.git
cd project_name

2. Install dependencies
pip install -r requirements.txt

3. Configuration
Edit config.py and fill in:
DB_CONFIG —— Remote mall database connection details
SM4_KEY —— National cryptographic encryption key
GJF_PREFIX —— Coupon template prefix
Modify core program code according to your own business logic and in-code comments
4. Start
python app.py # Development environment
or
gunicorn -w 2 -b 0.0.0.0:8000 app:app # Production environment
## 🚀 Usage Guide

### Administrator: Creating an Activity

1. Visit `http://your_domain/admin/login` in your browser and log in to the admin panel
2. Create a new activity: fill in the activity code, name, open time slots, and max draws per user
3. Configure prizes: select coupon names from the remote coupon library, set rank, winning probability, and stock (the total probability of all prizes must not exceed 1, and the remainder is the non-winning probability)
4. Edit the rich-text introduction (optional)
5. After saving, distribute the activity page link `http://your_domain/activity/<activity_code>` to users

### User: Participating in the Draw

1. Open the activity link and read the rich-text introduction
2. Enter your mobile number and click "🍹 Shake to Grab Coupons"
3. Unregistered users should follow the on-screen guide to scan and register, then return and retry
4. After winning, the coupon is automatically issued to the mall account; check it in the mini-program using your mobile number

### Mid-Campaign Adjustments

Go to the activity detail page in the admin panel, where you can directly modify stock (not below the already issued quantity), winning probabilities, and the rich-text introduction. Changes take effect immediately upon saving, no restart required.


## ❓ FAQ

<details>
<summary>Do the probabilities have to sum up to exactly 1?</summary>

No. The total probability of all prizes just needs to not exceed 1; the remaining probability automatically becomes the fallback "non-winning" probability.
</details>

<details>
<summary>Can the stock be reduced?</summary>

Yes, but it cannot be reduced below the quantity already issued. Both frontend and backend have validation.
</details>

<details>
<summary>What if I won but the coupon hasn't arrived?</summary>

If coupon issuance fails, the system automatically rolls back the stock and the winning record, and users can try again. Meanwhile, please check whether the remote coupon library API and the mall database connection are working properly.
</details>

## 📄 Open Source License

This project is open-sourced under the [MIT License](LICENSE).

> ⚠️ This project is an internal business practice project, intended for learning and exchange purposes only. No technical support is provided. Please do not use the default admin credentials in production environments.

---

*Translated by GLM-Flash*