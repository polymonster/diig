# Generate a new keystore file with one keypair
keytool -genkeypair `
  -alias upload-key `
  -keyalg RSA `
  -keysize 2048 `
  -validity 10000 `
  -keystore .\upload-keystore.jks