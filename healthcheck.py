import os
from termcolor import colored
from datetime import datetime
from colorama import init
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate,
    Table,
    TableStyle,
    Spacer,
    PageBreak,
    Paragraph,
)
from reportlab.lib.pagesizes import letter, landscape
from reportlab.lib.enums import TA_LEFT, TA_CENTER
from reportlab.lib.units import inch
from tabulate import tabulate
import boto3
import re
from kubernetes import client, config
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders

# Initialize colorama
init()
# Initialize Kubernetes client
config.load_incluster_config()
# Define constants
NAMESPACES = [
    "default",
    "kube-system",
]
# Colour code
GREEN = "green"
RED = "red"
BOLD = "bold"
NC = "white"
ORANGE = "orange"
# Pdf directory
output_directory = os.getcwd()
# Email
recipients_str = os.environ.get("recipients", "")
recipients = recipients_str.split(",") if recipients_str else []
# minimum eks version
minimum_eks_version = float(os.environ.get("minimum_eks_version", 0))
# AWS SPECIFIC
cloud_provider = os.environ.get("CLOUD_PROVIDER")


# Function to print messages with color
def print_color(message, color):
    print(colored(message, color))


# def list_aws_subnets(profile):
#     try:
#         # Check if the cloud provider is AWS
#         if cloud_provider != "aws":
#             print("Cloud provider is not AWS. Skipping AWS-related code.")
#             return None, "SKIPPED"

#         print("# Checking Subnet Count #")

#         # Get the region from the IAM role
#         region = boto3.session.Session().region_name
#         if not region:
#             error_message = "Failed to retrieve AWS region from IAM role."
#             print(error_message)
#             return None, "FAILED"

#         # Initialize Boto3 session with IAM role credentials
#         session = boto3.Session(region_name=region)

#         ec2 = session.client("ec2")
#         vpc_ids = ec2.describe_vpcs()["Vpcs"]
#         vpc_id = vpc_ids[0]["VpcId"]

#         subnets = ec2.describe_subnets(Filters=[{"Name": "vpc-id", "Values": [vpc_id]}])["Subnets"]

#         # Prepare data for the subnet table
#         subnet_table_data = []
#         header = ["Name", "Subnet ID", "Total IPs", "Used IPs", "Free IPs"]
#         subnet_table_data.append(header)

#         for subnet in subnets:
#             name = next((tag["Value"] for tag in subnet.get("Tags", []) if tag["Key"] == "Name"), None)
#             enis = ec2.describe_network_interfaces(Filters=[{"Name": "subnet-id", "Values": [subnet["SubnetId"]]}])["NetworkInterfaces"]
#             used_ips = str(len(enis))
#             free_ips = subnet["AvailableIpAddressCount"]
#             total_ips = int(used_ips) + free_ips
#             row_data = [name, subnet["SubnetId"], total_ips, used_ips, free_ips]
#             subnet_table_data.append(row_data)

#         # Calculate subnet_status based on your criteria
#         subnet_status = "PASSED" if all(subnet["AvailableIpAddressCount"] >= 20 for subnet in subnets) else "FAILED"

#         print("# Subnet calculations completed #")
#         return subnet_table_data, subnet_status
#     except Exception as e:
#         print(f"Error listing subnets: {str(e)}")
#         return None, "FAILED"


# Function to check if nodes are in a ready state
def check_nodes_ready():
    """
    Checks the status of all nodes in the cluster and returns
    `True` if all nodes are ready, `False` if one or more nodes are not ready,
    and a list of nodes that are not ready.
    """
    # Initialize lists to collect node information
    ready_nodes = []
    not_ready_nodes = []
    print_color("# Checking Node Status #", NC)
    try:
        # Load Kubernetes configuration from service account
        config.load_incluster_config()

        # Initialize Kubernetes API client
        api = client.CoreV1Api()

        # Get the list of nodes
        nodes = api.list_node().items

        if not nodes:
            print_color("No nodes found.", RED)
            return "FAILED", []
        # Calculate column widths based on the longest values
        max_node_name_width = max(len(node.metadata.name) for node in nodes)
        max_status_width = len("Status")
        max_version_width = len("Version")
        # Create a list to store the rows of the table
        node_table_output = []
        # Print the table header with "Name", "Status", and "Version" (only once)
        node_table_output.append(
            [
                "Name".ljust(max_node_name_width),
                "Version".ljust(max_version_width),
                "Status".ljust(max_status_width),
            ]
        )
        # Placeholder logic for node readiness checking
        for node in nodes:
            node_name = node.metadata.name
            conditions = node.status.conditions
            ready = False
            version = (
                node.status.node_info.kubelet_version
                if node.status.node_info and node.status.node_info.kubelet_version
                else "N/A"
            )
            # Extract the version number using a regular expression
            version_match = re.search(r"(\d+\.\d+)", version)
            if version_match:
                version_trimmed = version_match.group(1)
            else:
                version_trimmed = version
            for condition in conditions:
                if condition.type == "Ready" and condition.status == "True":
                    ready = True
            if not node_name.startswith("fargate"):
                if ready:
                    ready_nodes.append(node_name)
                    node_info = (node_name, "Ready", GREEN, version_trimmed)
                else:
                    not_ready_nodes.append(node_name)
                    node_info = (node_name, "Not Ready", RED, version_trimmed)
                status_formatted = node_info[1].ljust(max_status_width)
                version_formatted = node_info[3].ljust(max_version_width)
                node_table_output.append(
                    [
                        node_info[0].ljust(max_node_name_width),
                        version_formatted,
                        status_formatted,
                    ]
                )
                # Check if the version is below 1.25
                if float(version_trimmed) < minimum_eks_version:
                    print_color(
                        f"Node '{node_name}' has a version below {minimum_eks_version} i.e {version_trimmed}",
                        RED,
                    )

        # Check if any node is not ready and return result accordingly
        if not_ready_nodes:
            result = (
                f"Some nodes are not in a ready state: {', '.join(not_ready_nodes)}"
            )
            print_color(result, RED)
            return "FAILED", node_table_output
        else:
            result = "All nodes are in a ready state."
            print_color(result, GREEN)
            return "PASSED", node_table_output
    except Exception as e:
        print_color("Error while checking node status:", RED)
        print_color(str(e), RED)
        return "FAILED", []

# Function to check if pods are running
def check_pods_running():
    """
    Check the status of pods in the specified namespaces.
    Returns:
        True if all pods in the specified namespaces are ready (including "Completed" and "Succeeded"),
        False if one or more pods are not ready, and a list of pods that are not ready.
    """
    # Initialize a list to collect pod information
    pod_info = []
    problematic_pods = []  # To store problematic pods
    print_color("# Checking Pods Status #", NC)
    all_pods_running = True  # Track if all pods are running in all namespaces

    try:
        # Load Kubernetes configuration from service account
        config.load_incluster_config()

        # Initialize Kubernetes API client
        api = client.CoreV1Api()

        # Iterate through namespaces and collect pod info
        for namespace in NAMESPACES:
            if namespace != "":
                pods = api.list_namespaced_pod(namespace).items
                for pod in pods:
                    pod_name = pod.metadata.name
                    pod_status = pod.status.phase
                    pod_info.append((namespace, pod_name, pod_status))
                    if pod_status not in ["Running", "Completed", "Succeeded"]:
                        all_pods_running = (
                            False  # Set to False if any pod is not running
                        )
                        problematic_pods.append((namespace, pod_name))

        # Calculate the appropriate column widths with a minimum width of 10 for the Status column
        max_namespace_width = max(len(namespace) for namespace, _, _ in pod_info)
        max_pod_width = max(len(pod_name) for _, pod_name, _ in pod_info)
        max_status_width = max(
            max(len(pod_status), 10) for _, _, pod_status in pod_info
        )
        # Create a list to store the rows of the table
        pod_table_output = []
        # Print the table header
        pod_table_output.append(
            [
                "Namespace".ljust(max_namespace_width),
                "Pod".ljust(max_pod_width),
                "Status".ljust(max_status_width),
            ]
        )
        # Print pod info with proper formatting
        for namespace, pod_name, pod_status in pod_info:
            namespace_formatted = namespace.ljust(max_namespace_width)
            pod_name_formatted = pod_name.ljust(max_pod_width)
            pod_status_formatted = pod_status.ljust(max_status_width)
            if pod_status in ["Running", "Completed", "Succeeded"]:
                pod_table_output.append(
                    [namespace_formatted, pod_name_formatted, pod_status_formatted]
                )
            else:
                pod_table_output.append(
                    [namespace_formatted, pod_name_formatted, pod_status_formatted]
                )

        if all_pods_running:
            print_color("All pods are in Running state", GREEN)
        else:
            print_color("Some pods are not in Running state", RED)
            print_color("Problematic Pods:", RED)
            for namespace, pod_name in problematic_pods:
                print_color(f"Namespace: {namespace}, Pod: {pod_name}", RED)
            return "FAILED", pod_table_output

        return "PASSED", pod_table_output
    except Exception as e:
        print_color("Error while checking pod status:", RED)
        print_color(str(e), RED)
        return "FAILED", []

# Function to check if Velero backup is present
def check_velero_backup():
    """Check if a Velero backup is present.

    Returns:
        "PASSED" if a backup is present and in a completed state,
        "FAILED" if no backup is present or if a backup is not in a completed state.
    """
    # Initialize a list to collect backup information
    backup_info = []
    incomplete_backups = []  # To store names of incomplete backups
    print_color("# Checking Velero Backups #", NC)

    try:
        # Load kubeconfig from default location or service account
        config.load_incluster_config()

        # Create Kubernetes API client
        api_instance = client.CustomObjectsApi()

        # Retrieve Velero backups
        backups = api_instance.list_cluster_custom_object(
            group="velero.io", version="v1", plural="backups"
        )["items"]

        # Check if no backups are found
        if not backups:
            print_color("No backups found.", RED)
            return "FAILED", []

        # Sort backups by creation timestamp in descending order
        backups.sort(key=lambda x: x["metadata"]["creationTimestamp"], reverse=True)

        # Include only the last backup
        for backup in backups[:1]:
            backup_name = backup["metadata"]["name"]
            backup_status = backup["status"]["phase"]
            backup_info.append((backup_name, backup_status))

            if "Completed" not in backup_status:
                incomplete_backups.append(backup_name)

            # Calculate column widths based on the longest values
            max_backup_name_width = max(
                len(backup["metadata"]["name"]) for backup in backups
            )
            max_status_width = max(
                max(len(backup_status), 10) for _, backup_status in backup_info
            )

            # Create a list to store the rows of the table
            backup_table_output = []

            # Print the table header with "Name" and "Status"
            backup_table_output.append(
                ["Name".ljust(max_backup_name_width), "Status".ljust(max_status_width)]
            )

            # Print backup info with proper formatting
            for backup_name, backup_status in backup_info:
                name_formatted = backup_name.ljust(max_backup_name_width)
                status_formatted = backup_status.ljust(max_status_width)

                if "Completed" not in backup_status:
                    backup_table_output.append([name_formatted, status_formatted])
                else:
                    backup_table_output.append([name_formatted, status_formatted])

            # Check if any backup is not in a completed state and return result accordingly
            if incomplete_backups:
                print_color("Some backups are not in a completed state:", RED)
                for backup_name in incomplete_backups:
                    print_color(f"Backup Name: {backup_name}", RED)
                return "FAILED", backup_table_output

            print_color("All backups are in a completed state", GREEN)
            return "PASSED", backup_table_output
    except Exception as e:
        print_color("Error while checking Velero backup status:", RED)
        print_color(str(e), RED)
        return "FAILED", []

# Health check summary data
# Function to generate summary
summary_data = []

def generate_summary(node_status, pods_status, backup_status):
    """
    Generate a healthcheck summary based on the results of the `check_nodes_ready()`,
    `check_pods_ready()`, and `check_backup_present()` functions.
    Args:
      node_status: The status of the nodes, either "PASSED" or "FAILED".
      pods_status: The status of the pods, either "PASSED" or "FAILED".
      backup_status: The status of the Velero backup, either "PASSED" or "FAILED".
    Returns:
      None.
    """
    print_color("# Healthcheck Summary #", NC)
    # lear the summary data
    summary_data.clear()

    # Define a function to add a summary item
    def add_summary_item(title, status):
        summary_data.append([title, status])
        print_color(f"{title}: {status}", GREEN if status == "PASSED" else RED)

    add_summary_item("Check", "Status")
    add_summary_item("All Nodes are in Ready state", node_status)
    add_summary_item("All Pods are in Running state", pods_status)
    add_summary_item("Velero backup is present", backup_status)


# Function to generate pdf
def generate_result_table(title, data, elements, table_type, header_color="#337AB7"):
    """
    Generate a table with the results of a specific health check.
    Args:
      title: The title of the table.
      data: The data to be displayed in the table.
      elements: The list of report elements to which the table will be added.
      header_color: The color for the table header.

    Returns:
      None.
    """
    if not data:
        return
    try:
        # Calculate column widths based on the maximum content length for each column
        col_widths = [
            max(len(str(row[i])) for row in data) for i in range(len(data[0]))
        ]
        # Create a table style with specific settings
        table_style = [
            (
                "BACKGROUND",
                (0, 0),
                (-1, 0),
                colors.HexColor(header_color),
            ),  # Header background color
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),  # Header text color
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),  # Center-align all cells
            ("FONTNAME", (0, 0), (-1, 0), "Courier-Bold"),  # Header font
            ("BOTTOMPADDING", (0, 0), (-1, 0), 12),  # Padding for the header
            (
                "BACKGROUND",
                (0, 1),
                (-1, -1),
                colors.beige,
            ),  # Background color for content rows
            ("GRID", (0, 0), (-1, -1), 1, colors.black),  # Add grid lines
        ]
        # Loop through the data rows and apply cell background color based on table type
        for i in range(1, len(data)):
            row = data[i]  # Get the row data
            row_status = row[-1]  # Assuming the status is in the last column of the row
            # Apply different row coloring conditions based on the table type
            if table_type == "summary":
                if "FAILED" in row_status:
                    table_style.extend([("BACKGROUND", (0, i), (-1, i), colors.red)])
                else:
                    table_style.extend([("BACKGROUND", (0, i), (-1, i), colors.white)])
            elif table_type == "nodes":
                row_version = row[-2]
                # Customize row coloring conditions for the "nodes" table
                if "Ready" in row_status:
                    # Check if the version is below 1.25
                    if float(row_version) < minimum_eks_version:
                        table_style.extend(
                            [("BACKGROUND", (0, i), (-1, i), colors.yellow)]
                        )
                    else:
                        table_style.extend(
                            [("BACKGROUND", (0, i), (-1, i), colors.white)]
                        )
                else:
                    table_style.extend([("BACKGROUND", (0, i), (-1, i), colors.red)])
            elif table_type == "pods":
                # Customize row coloring conditions for the "pods" table
                if "Running" in row_status:
                    table_style.extend([("BACKGROUND", (0, i), (-1, i), colors.white)])
                elif "Succeeded" in row_status:
                    table_style.extend([("BACKGROUND", (0, i), (-1, i), colors.white)])
                else:
                    table_style.extend([("BACKGROUND", (0, i), (-1, i), colors.red)])

            elif table_type == "backup":
                # Customize row coloring conditions for the "pods" table
                if "Completed" not in row_status:
                    table_style.extend([("BACKGROUND", (0, i), (-1, i), colors.red)])
                else:
                    table_style.extend([("BACKGROUND", (0, i), (-1, i), colors.white)])
        # Set column widths for the header row and data rows
        table_style.extend(
            [
                ("COLWIDTH", (i, 0), (i, -1), col_widths[i])
                for i in range(len(col_widths))
            ]
        )
        # Create the table and apply the style
        table = Table(data, repeatRows=1)
        table.setStyle(TableStyle(table_style))

        # Create a title paragraph
        title_style = getSampleStyleSheet()["Heading2"]
        title_style.alignment = TA_LEFT  # Left-align the title
        title_paragraph = Paragraph(title, title_style)

        # Add the title and table to the elements
        elements.append(title_paragraph)
        elements.append(table)
        elements.append(Spacer(1, 12))  # Add space after the table
    except Exception as e:
        print_color(f"Error while generating result table: {str(e)}", RED)


def send_email(
    recipients, cluster_name, pdf_file_path, node_status, pods_status, backup_status
):
    """
    Send an email with the health check report as an attachment and include the health check summary.
    Args:
        recipients: List of email recipients.
        cluster_name: Name of the cluster.
        pdf_file_path: Path to the PDF file to be attached.
        node_status: The status of the nodes, either "PASSED" or "FAILED".
        pods_status: The status of the pods, either "PASSED" or "FAILED".
        backup_status: The status of the Velero backup, either "PASSED" or "FAILED".
    Returns:
        None.
    """
    # Email configuration
    sender_email = os.environ.get("SENDER_EMAIL")
    sender_password = os.environ.get("SENDER_PASSWORD")
    smtp_server = os.environ.get("SMTP_SERVER")
    smtp_port = int(os.environ.get("SMTP_PORT", 587))

    if not all([sender_email, sender_password, smtp_server]):
        raise ValueError(
            "Email configuration missing. Make sure to set SENDER_EMAIL, SENDER_PASSWORD, and SMTP_SERVER in the environment."
        )
    subject = f"EKS Cluster Health Report for {cluster_name}"
    # Create a multipart message
    msg = MIMEMultipart()
    msg["From"] = sender_email
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = subject
    # Define colors for header background
    header_color = "#337AB7"  # Light Blue
    # Generate HTML content for health check summary
    summary_html = f"""
    <html>
    <head>
        <style>
            /* Style for the summary table */
            table {{
                width: 50%;
                border-collapse: collapse;
                margin-top: 20px;
                margin-bottom: 20px;
                font-size: 16px;
            }}
            th, td {{
                padding: 6px;
                text-align: left;
                border: 1px solid #ddd;
                font-size: 16px; /* Set font size */
                color: black !important; /* Set font color to black */
            }}
            th {{
                background-color: {header_color};
                color: white;
            }}
            /* Style for the email body container */
            .email-container {{
                background-color: #FFFFFF;
                padding: 20px;
            }}
            .passed {{
                background-color: #00FF00; /* Green */
                color: white;
            }}
            .failed {{
                background-color: #FF0000; /* Red */
                color: white;
            }}
        </style>
    </head>
    <body>
        <div class="email-container" style="font-family: Arial, sans-serif;">
            <p>We are pleased to provide you with the latest EKS (Elastic Kubernetes Service) Cluster Health Report for your review.</p>
            <p>Please take a moment to review the report carefully, as it contains crucial information about the current state of your Kubernetes cluster.</p>
            <!-- Summary Table -->
            <h2>Healthcheck Summary</h2>
            <table>
                <tr>
                    <th>Check</th>
                    <th>Status</th>
                </tr>
                <tr>
                    <td>All Nodes are in Ready state</td>
                    <td class="{node_status.lower()}">{node_status}</td>
                </tr>
                <tr>
                    <td>All Pods are in Running state</td>
                    <td class="{pods_status.lower()}">{pods_status}</td>
                </tr>
                <tr>
                    <td>Velero backup is present</td>
                    <td class="{backup_status.lower()}">{backup_status}</td>
                </tr>
            </table>
        </div>
    </body>
    </html>
    """
    # Attach HTML content
    msg.attach(MIMEText(summary_html, "html"))
    # Attach the PDF file
    try:
        with open(pdf_file_path, "rb") as attachment:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(attachment.read())
            encoders.encode_base64(part)
            part.add_header(
                "Content-Disposition", f"attachment; filename= {pdf_file_path}"
            )
            msg.attach(part)
    except Exception as e:
        raise Exception(f"Failed to attach PDF file: {e}")
    # Send the email
    try:
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(sender_email, sender_password)
            server.sendmail(sender_email, recipients, msg.as_string())
    except Exception as e:
        raise Exception(f"Failed to send email: {e}")  ###Main function

if __name__ == "__main__":
    ##Print start time
    start_time = datetime.now()
    try:
        # Run prechecks
        # Example usage
        cluster_name = os.environ.get("cluster_name")
        if cluster_name:
            print("Cluster Name:", cluster_name)
        else:
            print("Failed to retrieve cluster name.")
        print_color(
            f"####################### Starting Health Checks for {cluster_name} cluster #######################",
            GREEN,
        )
        # Get the current date and time as a formatted string
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

        # Generate the PDF file name with cluster name and timestamp
        pdf_file_name = f"{cluster_name}_health_check_report_{timestamp}.pdf"

        # Combine the directory path and file name to create the full file path
        pdf_file_path = os.path.join(output_directory, pdf_file_name)

        doc = SimpleDocTemplate(pdf_file_path, pagesize=landscape(letter))
        elements = []

        # Add a header to the PDF report
        header_style = getSampleStyleSheet()["Heading1"]
        header_style.alignment = TA_CENTER  # Center-align the header title
        # Use a bold font for the header title
        header_style.fontName = "Helvetica-Bold"
        header_style.textColor = colors.HexColor("#337AB7")
        # Blue color for the header title
        header_text = f"Health Check Report of  {cluster_name}"
        header_paragraph = Paragraph(header_text, header_style)
        elements.append(header_paragraph)
        elements.append(Spacer(1, 12))  # Add some space after the header title

        # Add an overview section at the start with left alignment
        overview_style = getSampleStyleSheet()["Heading2"]
        overview_style.alignment = TA_LEFT  # Left-align the overview title
        overview_text = "Overview:"
        overview_paragraph = Paragraph(overview_text, overview_style)
        elements.append(overview_paragraph)

        # Add information related to the script
        script_info_text = """
        This comprehensive report is designed to provide you with a detailed health assessment of EKS cluster. It covers three critical aspects: node status, pod status, Velero backup status and Subnets .<br/><br/>

        <b>Subnets Count:</b> Verifies that all subnets in the account to ensure sufficient ipaddresses are available.<br/><br/>

        <b>Node Status:</b> Verifies that all nodes in the cluster are in a ready state, ensuring the foundation of cluster is stable.<br/><br/>

        <b>Pod Status:</b> Assesses the running status of pods across different namespaces, ensuring all system pods are operating smoothly.<br/><br/>

        <b>Velero Backup Status:</b> Checks if Velero backups are present and completed, safeguarding your cluster's data and configurations.<br/><br/>

        This report is designed to empower you with actionable insights, enabling you to make informed decisions and ensure the reliability of the EKS cluster. Our commitment to excellence in cluster health is reflected in every aspect of this assessment.

        """
        elements.append(Paragraph(script_info_text, getSampleStyleSheet()["Normal"]))
        # Add some space after the script information
        elements.append(Spacer(1, 12))

        # Display cluster information
        cluster_info_text = f"<b>Cluster:</b> {cluster_name}"
        elements.append(Paragraph(cluster_info_text, getSampleStyleSheet()["Normal"]))
        # Add some space after the script information
        elements.append(Spacer(1, 12))

        # Display start time, end time, and time elapsed in bold
        elements.append(
            Paragraph(
                f"<font size='10'><b>Start Time:</b></font> {start_time.strftime('%Y-%m-%d %H:%M:%S')}",
                getSampleStyleSheet()["Normal"],
            )
        )
        # Add some space after the script information
        elements.append(Spacer(1, 12))

        # Health check sections with colored headers
        node_status, node_table_output = check_nodes_ready()
        generate_result_table(
            "<font size='10'><b>Node Status:</b></font>",
            node_table_output,
            elements,
            table_type="nodes",
            header_color="#337AB7",
        )
        pods_status, pod_table_output = check_pods_running()
        generate_result_table(
            "<font size='10'><b>Pods Status:</b></font>",
            pod_table_output,
            elements,
            table_type="pods",
            header_color="#337AB7",
        )
        backup_status, backup_table_output = check_velero_backup()
        generate_result_table(
            "<font size='10'><b>Velero Status:</b></font>",
            backup_table_output,
            elements,
            table_type="backup",
            header_color="#337AB7",
        )
        # Generate healthcheck summary
        summary = generate_summary(node_status, pods_status, backup_status)
        generate_result_table(
            "<font size='10'><b>Health Check Summary:</b></font>",
            summary_data,
            elements,
            table_type="summary",
            header_color="#337AB7",
        )

        elements.append(Spacer(1, 12))

        # Record the end time
        end_time = datetime.now()
        time_elapsed = end_time - start_time
        elements.append(
            Paragraph(
                f"<b>End Time:</b> {end_time.strftime('%Y-%m-%d %H:%M:%S')}",
                getSampleStyleSheet()["Normal"],
            )
        )
        elements.append(Spacer(1, 12))
        # Add some space after the cluster information and timestamps
        elements.append(
            Paragraph(
                f"<b>Time Elapsed:</b> {str(time_elapsed)} seconds",
                getSampleStyleSheet()["Normal"],
            )
        )
        # Build the PDF document with the elements
        doc.build(elements)
        # Print the PDF file path
        print_color(f"PDF report generated: {pdf_file_path}", GREEN)
        # send email
        send_email(
            recipients,
            cluster_name,
            pdf_file_path,
            node_status,
            pods_status,
            backup_status,
        )
    except Exception as e:
        print_color(f"Error: {str(e)}", RED)
    except KeyboardInterrupt:
        # Handle keyboard interruption (Ctrl+C)
        print_color("\nKeyboard interruption detected. Exiting gracefully.", RED)
        exit(1)
    finally:
        # Calculate and print execution time
        end_time = datetime.now()
        execution_time = end_time - start_time
        print_color(f"Execution time: {execution_time}", NC)
        print_color(
            "####################### Health Checks Completed #######################",
            NC,
        )
