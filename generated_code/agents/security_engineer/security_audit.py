import subprocess

class SecurityAudit:
    """
    Class to perform security audits and provide recommendations.
    """
    @staticmethod
    def run_os_query(query: str):
        """
        Run a security-related OS query (e.g., list open ports).
        """
        try:
            result = subprocess.check_output(query, shell=True, text=True)
            return result
        except subprocess.CalledProcessError as e:
            return f"Error running OS query: {e}"

    @staticmethod
    def check_open_ports():
        """
        Check open ports on the system.
        """
        return SecurityAudit.run_os_query("netstat -tuln")

    @staticmethod
    def check_installed_packages():
        """
        Check installed packages for potential vulnerabilities.
        """
        return SecurityAudit.run_os_query("dpkg-query -l")

# Example usage
if __name__ == "__main__":
    audit = SecurityAudit()
    print("Open Ports:")
    print(audit.check_open_ports())
    print("\nInstalled Packages:")
    print(audit.check_installed_packages())