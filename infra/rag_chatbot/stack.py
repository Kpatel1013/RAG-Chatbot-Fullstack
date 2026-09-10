from aws_cdk import (
    CfnOutput,
    Duration,
    RemovalPolicy,
    SecretValue,
    Stack,
    aws_ec2 as ec2,
    aws_ecr as ecr,
    aws_ecs as ecs,
    aws_elasticloadbalancingv2 as elbv2,
    aws_logs as logs,
    aws_rds as rds,
    aws_secretsmanager as secretsmanager,
)
from constructs import Construct


class RagChatbotStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # --- network ---
        vpc = ec2.Vpc(
            self,
            "Vpc",
            max_azs=2,
            nat_gateways=0,
            subnet_configuration=[
                ec2.SubnetConfiguration(name="Public", subnet_type=ec2.SubnetType.PUBLIC, cidr_mask=24),
                ec2.SubnetConfiguration(name="Isolated", subnet_type=ec2.SubnetType.PRIVATE_ISOLATED, cidr_mask=24),
            ],
        )

        alb_sg = ec2.SecurityGroup(self, "AlbSg", vpc=vpc)
        alb_sg.add_ingress_rule(ec2.Peer.any_ipv4(), ec2.Port.tcp(80))

        backend_sg = ec2.SecurityGroup(self, "BackendSg", vpc=vpc)
        frontend_sg = ec2.SecurityGroup(self, "FrontendSg", vpc=vpc)
        backend_sg.connections.allow_from(alb_sg, ec2.Port.tcp(8000))
        frontend_sg.connections.allow_from(alb_sg, ec2.Port.tcp(80))

        alb = elbv2.ApplicationLoadBalancer(self, "Alb", vpc=vpc, internet_facing=True, security_group=alb_sg)

        backend_tg = elbv2.ApplicationTargetGroup(
            self, "BackendTg", vpc=vpc, port=8000, target_type=elbv2.TargetType.IP,
            health_check=elbv2.HealthCheck(path="/health", interval=Duration.seconds(30)),
        )
        frontend_tg = elbv2.ApplicationTargetGroup(
            self, "FrontendTg", vpc=vpc, port=80, target_type=elbv2.TargetType.IP,
            health_check=elbv2.HealthCheck(path="/", interval=Duration.seconds(30)),
        )

        listener = alb.add_listener("Http", port=80, open=True, default_target_groups=[frontend_tg])
        listener.add_action(
            "Api",
            priority=10,
            conditions=[elbv2.ListenerCondition.path_patterns(["/api", "/api/*", "/health", "/docs", "/docs/*"])],
            action=elbv2.ListenerAction.forward([backend_tg]),
        )

        # --- storage ---
        db = rds.DatabaseInstance(
            self,
            "Database",
            engine=rds.DatabaseInstanceEngine.postgres(version=rds.PostgresEngineVersion.VER_16),
            instance_type=ec2.InstanceType.of(ec2.InstanceClass.T3, ec2.InstanceSize.MICRO),
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_ISOLATED),
            credentials=rds.Credentials.from_generated_secret("ragadmin"),
            database_name="ragdb",
            allocated_storage=20,
            removal_policy=RemovalPolicy.DESTROY,
            deletion_protection=False,
            backup_retention=Duration.days(1),
        )
        db.connections.allow_from(backend_sg, ec2.Port.tcp(5432))

        deepseek_secret = secretsmanager.Secret(
            self,
            "DeepSeekKey",
            secret_name="rag-chatbot/deepseek-api-key",
            secret_string_value=SecretValue.unsafe_plain_text(
                self.node.try_get_context("deepseekApiKey") or "REPLACE_ME"
            ),
        )

        backend_repo = ecr.Repository(
            self, "BackendRepo", repository_name="rag-chatbot-backend",
            removal_policy=RemovalPolicy.DESTROY, empty_on_delete=True,
        )
        frontend_repo = ecr.Repository(
            self, "FrontendRepo", repository_name="rag-chatbot-frontend",
            removal_policy=RemovalPolicy.DESTROY, empty_on_delete=True,
        )

        # --- services ---
        cluster = ecs.Cluster(self, "Cluster", vpc=vpc)
        cors = f"http://{alb.load_balancer_dns_name}"

        backend_task = ecs.FargateTaskDefinition(self, "BackendTask", cpu=1024, memory_limit_mib=2048)
        backend_task.add_container(
            "Backend",
            image=ecs.ContainerImage.from_ecr_repository(backend_repo, tag="latest"),
            logging=ecs.LogDrivers.aws_logs(
                stream_prefix="backend",
                log_group=logs.LogGroup(self, "BackendLogs", retention=logs.RetentionDays.ONE_WEEK, removal_policy=RemovalPolicy.DESTROY),
            ),
            environment={"CORS_ORIGINS": cors},
            secrets={
                "DEEPSEEK_API_KEY": ecs.Secret.from_secrets_manager(deepseek_secret),
                "POSTGRES_HOST": ecs.Secret.from_secrets_manager(db.secret, "host"),
                "POSTGRES_USER": ecs.Secret.from_secrets_manager(db.secret, "username"),
                "POSTGRES_PASSWORD": ecs.Secret.from_secrets_manager(db.secret, "password"),
                "POSTGRES_DB": ecs.Secret.from_secrets_manager(db.secret, "dbname"),
            },
            port_mappings=[ecs.PortMapping(container_port=8000)],
        )
        backend_svc = ecs.FargateService(
            self, "BackendService", cluster=cluster, task_definition=backend_task,
            assign_public_ip=True, security_groups=[backend_sg],
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
        )
        backend_svc.attach_to_application_target_group(backend_tg)

        frontend_task = ecs.FargateTaskDefinition(self, "FrontendTask", cpu=256, memory_limit_mib=512)
        frontend_task.add_container(
            "Frontend",
            image=ecs.ContainerImage.from_ecr_repository(frontend_repo, tag="latest"),
            logging=ecs.LogDrivers.aws_logs(
                stream_prefix="frontend",
                log_group=logs.LogGroup(self, "FrontendLogs", retention=logs.RetentionDays.ONE_WEEK, removal_policy=RemovalPolicy.DESTROY),
            ),
            port_mappings=[ecs.PortMapping(container_port=80)],
        )
        frontend_svc = ecs.FargateService(
            self, "FrontendService", cluster=cluster, task_definition=frontend_task,
            assign_public_ip=True, security_groups=[frontend_sg],
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
        )
        frontend_svc.attach_to_application_target_group(frontend_tg)

        # --- outputs ---
        CfnOutput(self, "AppUrl", value=f"http://{alb.load_balancer_dns_name}")
        CfnOutput(self, "BackendRepoUri", value=backend_repo.repository_uri)
        CfnOutput(self, "FrontendRepoUri", value=frontend_repo.repository_uri)
        CfnOutput(self, "ClusterName", value=cluster.cluster_name)
        CfnOutput(self, "BackendServiceName", value=backend_svc.service_name)
        CfnOutput(self, "FrontendServiceName", value=frontend_svc.service_name)
