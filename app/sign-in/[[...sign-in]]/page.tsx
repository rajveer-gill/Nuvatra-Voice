import { SignIn } from '@clerk/nextjs'
import AuthShell from '@/components/AuthShell'
import { clerkAppearance } from '@/lib/clerk-appearance'

export default function SignInPage() {
  return (
    <AuthShell headingId="sign-in-heading">
      <h1 id="sign-in-heading" className="sr-only">
        Sign in
      </h1>
      <SignIn
        appearance={clerkAppearance}
        routing="path"
        path="/sign-in"
        signUpUrl="/sign-up"
      />
    </AuthShell>
  )
}
