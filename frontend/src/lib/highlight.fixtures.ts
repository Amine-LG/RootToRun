// Small, complete resources covering the structures shown in lessons.
export const deploymentService = `apiVersion: apps/v1
kind: Deployment
metadata:
  name: web
  labels:
    app.kubernetes.io/name: web
  annotations:
    example.com/description: "web: public # endpoint"
spec:
  replicas: 3
  selector:
    matchLabels:
      app: web
  template:
    metadata:
      labels:
        app: web
    spec:
      containers:
        - name: web
          image: quay.io/example/web:1.0
          ports:
            - name: http
              containerPort: 8080
          env:
            - name: PORT
              value: "8080"
            - name: ENABLED
              value: 'true'
          readinessProbe:
            httpGet:
              path: /health
              port: http
            initialDelaySeconds: 5
          livenessProbe:
            httpGet:
              path: /health
              port: http
            periodSeconds: 10
          securityContext:
            allowPrivilegeEscalation: false
            readOnlyRootFilesystem: true
            runAsNonRoot: true
            capabilities:
              drop: [ALL]
          volumeMounts:
            - name: config
              mountPath: /etc/web
              readOnly: true
          resources:
            requests:
              cpu: 100m
              memory: 64Mi
      volumes:
        - name: config
          configMap:
            name: web-config
            defaultMode: 0755
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 1
      maxUnavailable: 0
---
apiVersion: v1
kind: Service
metadata:
  name: web
spec:
  selector: {app: web}
  ports:
    - name: http
      port: 80
      targetPort: 8080
  type: ClusterIP
`

export const configMap = `apiVersion: v1
kind: ConfigMap
metadata:
  name: web-config
  annotations:
    "example.com/quoted-key": "value: with a colon"
    'example.com/single-key': 'it''s # a string'
data:
  app.conf: |-
    key: value
    # this belongs to the string
    upstream: https://example.test/path#fragment
    nested:
      enabled: true

    still: a string # with a hash
  message: >+
    hello: world
    # also a string
  literal: |
    key: value
  folded: >
    key: value
  url: https://example.test/path#fragment # trailing comment
  quoted: "escaped \\"quote\\" # still a string"
  '8080': "0755"
`

export const route = `apiVersion: route.openshift.io/v1
kind: Route
metadata:
  name: web
  annotations:
    haproxy.router.openshift.io/timeout: 30s
    example.com/endpoint: https://web.example.test:8443/a#fragment
spec:
  host: web.example.test
  to:
    kind: Service
    name: web
    weight: 100
  port:
    targetPort: http
  tls:
    termination: edge
    insecureEdgeTerminationPolicy: Redirect
  wildcardPolicy: None
`

export const networkPolicy = `# Only the frontend can reach the web pods.
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-frontend
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: web
  policyTypes: [Ingress, Egress]
  ingress:
    - from:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: demo
          podSelector:
            matchLabels: {role: frontend}
      ports:
        - protocol: TCP
          port: 8080
  egress:
    - to:
        - ipBlock:
            cidr: 10.0.0.0/8
            except: [10.1.0.0/16]
      ports:
        - protocol: TCP
          port: 443
`

export const manifest = [deploymentService, configMap, route, networkPolicy].join('---\n')
