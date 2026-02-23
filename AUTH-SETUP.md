# Auth Setup (Clerk)

The site uses **Clerk** for authentication. Marketing pages are public; the **Dashboard** (Nuvatra Voice) is protected.

## Setup

1. **Sign up at [clerk.com](https://clerk.com)**

2. **Create an application** (e.g. "Nuvatra" or "Nuvatra HQ")

3. **Enable sign-in methods**  
   In Clerk Dashboard: Configure → Email, Password, and/or Google/GitHub OAuth

4. **Copy API keys**  
   In Clerk Dashboard: API Keys  
   - `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` (starts with `pk_`)  
   - `CLERK_SECRET_KEY` (starts with `sk_`)

5. **Local:** Create `.env.local` in the project root with the keys and redirect URLs (see `.env.local.example`).

6. **Production (required for a live site)**  
   The frontend runs on **Vercel** or **Netlify**. Add these as **Environment Variables** in that project’s dashboard:
   - `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` = your publishable key (pk_test_… or pk_live_…)
   - `CLERK_SECRET_KEY` = your secret key (sk_test_… or sk_live_…)
   - `NEXT_PUBLIC_CLERK_AFTER_SIGN_IN_URL` = `/dashboard`
   - `NEXT_PUBLIC_CLERK_AFTER_SIGN_UP_URL` = `/dashboard`
   - `NEXT_PUBLIC_API_URL` = your backend URL (e.g. `https://nuvatra-voice.onrender.com`)

   Without these on the host, sign-in and the dashboard will not work in production.

## Flow

- **Public:** Home, Products, Contact (marketing)
- **Protected:** `/dashboard` – Nuvatra Voice (Voice Call, Appointments, Dashboard)
- Unauthenticated users visiting `/dashboard` are redirected to Clerk sign-in
- After sign-in/sign-up, users are redirected to `/dashboard`
