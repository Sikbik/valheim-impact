using System;
using System.Runtime.InteropServices;
using System.Security.Cryptography;

namespace ValheimImpact.Core
{
    public static class Fingerprint
    {
        [DllImport("libcrypto.so.3", EntryPoint = "SHA256", CallingConvention = CallingConvention.Cdecl)]
        private static extern IntPtr NativeSha256([In] byte[] data, UIntPtr length, [Out] byte[] digest);
        private static readonly bool native = Probe();
        public static string Backend { get { return native ? "OpenSSL 3 native SHA256" : "managed SHA256 fallback"; } }
        private static string Format(byte[] digest) { return BitConverter.ToString(digest).Replace("-", "").ToLowerInvariant(); }
        private static bool Probe()
        {
            try
            {
                byte[] digest = new byte[32];
                return NativeSha256(new byte[] { 97, 98, 99 }, new UIntPtr(3), digest) != IntPtr.Zero &&
                    Format(digest) == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad";
            }
            catch (DllNotFoundException) { return false; }
            catch (EntryPointNotFoundException) { return false; }
            catch (BadImageFormatException) { return false; }
        }
        public static string Hex(byte[] data)
        {
            if (data == null) throw new ArgumentNullException("data");
            if (native)
            {
                byte[] digest = new byte[32];
                if (NativeSha256(data, new UIntPtr((uint)data.Length), digest) == IntPtr.Zero)
                    throw new CryptographicException("Native texture fingerprint failed");
                return Format(digest);
            }
            using (var sha = SHA256.Create()) return Format(sha.ComputeHash(data));
        }
    }
}
