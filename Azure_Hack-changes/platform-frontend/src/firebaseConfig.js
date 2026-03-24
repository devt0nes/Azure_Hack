import { initializeApp } from 'firebase/app'
import { getAuth, GoogleAuthProvider, signInWithPopup, signOut } from 'firebase/auth'

const requiredEnv = {
  VITE_FIREBASE_API_KEY: import.meta.env.VITE_FIREBASE_API_KEY?.trim(),
  VITE_FIREBASE_AUTH_DOMAIN: import.meta.env.VITE_FIREBASE_AUTH_DOMAIN?.trim(),
  VITE_FIREBASE_PROJECT_ID: import.meta.env.VITE_FIREBASE_PROJECT_ID?.trim(),
  VITE_FIREBASE_STORAGE_BUCKET: import.meta.env.VITE_FIREBASE_STORAGE_BUCKET?.trim(),
  VITE_FIREBASE_MESSAGING_SENDER_ID: import.meta.env.VITE_FIREBASE_MESSAGING_SENDER_ID?.trim(),
  VITE_FIREBASE_APP_ID: import.meta.env.VITE_FIREBASE_APP_ID?.trim(),
}

const missing = Object.entries(requiredEnv)
  .filter(([, value]) => !value)
  .map(([key]) => key)

if (missing.length) {
  console.error(
    `[firebaseConfig] Missing Firebase env vars: ${missing.join(', ')}. ` +
    'Create platform-frontend/.env (not src/.env) and restart Vite.'
  )
}

const firebaseConfig = {
  apiKey: requiredEnv.VITE_FIREBASE_API_KEY,
  authDomain: requiredEnv.VITE_FIREBASE_AUTH_DOMAIN,
  projectId: requiredEnv.VITE_FIREBASE_PROJECT_ID,
  storageBucket: requiredEnv.VITE_FIREBASE_STORAGE_BUCKET,
  messagingSenderId: requiredEnv.VITE_FIREBASE_MESSAGING_SENDER_ID,
  appId: requiredEnv.VITE_FIREBASE_APP_ID,
}

const app = initializeApp(firebaseConfig)
export const auth = getAuth(app)
export const googleProvider = new GoogleAuthProvider()

export async function loginWithGoogle() {
  const result = await signInWithPopup(auth, googleProvider)
  const token = await result.user.getIdToken()
  return { user: result.user, token }
}

export async function logout() {
  await signOut(auth)
}

export async function getToken() {
  const user = auth.currentUser
  if (!user) throw new Error('Not authenticated')
  return user.getIdToken()  // auto-refreshes if expired
}