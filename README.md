# ReviewBoost AI 

An AI-powered product review optimization system that enhances product reviews and evaluates them using a reward-based (RL-style) scoring mechanism.

---

## 🔹 Features

* Image-based product analysis
* AI-generated product details and reviews
* Review improvement system
* RL-style scoring (before vs after comparison)

---

## 🔹 How It Works

1. Upload an image of a product
2. System analyzes and generates product details
3. Extracted review is improved using AI
4. System assigns:

   * Score before improvement
   * Score after improvement

---

## 🔹 RL Mapping

* **State:** Product review text
* **Action:** Improve review
* **Reward:** Score improvement

---

## 🔹 Tech Stack

* Frontend: React
* Backend: Python (FastAPI)
* AI: LLM APIs

---

## 🔹 Run Locally

### 1. Clone the repo

```bash
git clone https://github.com/your-username/ai-review-optimizer-rl.git
cd ai-review-optimizer-rl
```

---

### 2. Backend setup

```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python -m uvicorn main:app --reload
```

---

### 3. Frontend setup

```bash
cd frontend
npm install
npm run dev
```

---

## 🔹 Future Improvements

* Better scoring using advanced models
* Multi-step optimization (iterative improvements)
* User-controlled review tuning

---

## 🔹 Author

Adarsh Kumar
