<img src="https://r2cdn.perplexity.ai/pplx-full-logo-primary-dark%402x.png" style="height:64px;margin-right:32px"/>

## Arquitectura de Proxy TLS con HSM en Spring Boot

Basándome en tu escenario, te propongo varias soluciones productizadas para implementar un microservicio proxy que realice TLS offloading con firma de certificados almacenados en un HSM.

### Solución 1: Spring Cloud Gateway con PKCS\#11 Provider

Esta es la opción más integrada con el ecosistema Spring Boot:

**Arquitectura:**

- **Servicio Cliente (N)** → envía petición con header de host de destino
- **Proxy Gateway (Spring Cloud Gateway)** → intercepta, establece mTLS con HSM
- **Servicio Externo** → recibe petición firmada con certificado del HSM

**Implementación:**

```java
// 1. Configuración del Provider PKCS#11
@Configuration
public class HSMConfiguration {
    
    @PostConstruct
    public void setupHSMProvider() throws Exception {
        // Configurar el provider PKCS#11
        String configPath = "/path/to/hsm-config.cfg";
        Provider hsmProvider = new sun.security.pkcs11.SunPKCS11(configPath);
        Security.addProvider(hsmProvider);
    }
    
    @Bean
    public HttpClient customHttpClient() throws Exception {
        // Cargar el KeyStore desde el HSM
        KeyStore keyStore = KeyStore.getInstance("PKCS11", "SunPKCS11-HSM");
        keyStore.load(null, hsmPin.toCharArray());
        
        // Configurar SSLContext con el certificado del HSM
        SSLContext sslContext = SSLContexts.custom()
            .loadKeyMaterial(keyStore, hsmPin.toCharArray())
            .loadTrustMaterial(trustStore, null)
            .build();
        
        // Crear HttpClient con soporte para el HSM
        return HttpClient.create()
            .secure(spec -> spec.sslContext(sslContext));
    }
}
```

**Archivo de configuración HSM (`hsm-config.cfg`):**

```
name = HSM-Provider
library = /usr/lib/libpkcs11.so
slot = 0
```

**Configuración de Spring Cloud Gateway:**

```yaml
spring:
  cloud:
    gateway:
      routes:
        - id: external-service-route
          uri: https://external-service.com
          predicates:
            - Path=/api/**
          filters:
            - AddRequestHeader=X-Forwarded-Host, ${request.header.target-host}
      httpclient:
        ssl:
          use-insecure-trust-manager: false
```

**Filtro personalizado para routing dinámico:**

```java
@Component
public class DynamicRoutingFilter implements GlobalFilter, Ordered {
    
    @Override
    public Mono<Void> filter(ServerWebExchange exchange, GatewayFilterChain chain) {
        String targetHost = exchange.getRequest()
            .getHeaders()
            .getFirst("X-Target-Host");
        
        if (targetHost != null) {
            URI newUri = UriComponentsBuilder
                .fromUri(exchange.getRequest().getURI())
                .host(targetHost)
                .build()
                .toUri();
            
            ServerHttpRequest modifiedRequest = exchange.getRequest()
                .mutate()
                .uri(newUri)
                .build();
            
            return chain.filter(exchange.mutate()
                .request(modifiedRequest)
                .build());
        }
        
        return chain.filter(exchange);
    }
    
    @Override
    public int getOrder() {
        return -1;
    }
}
```


### Solución 2: Servicio Proxy Spring Boot con RestTemplate/WebClient

Enfoque más simple para un proxy dedicado:[^1_1][^1_2][^1_3]

```java
@RestController
@RequestMapping("/proxy")
public class TLSProxyController {
    
    private final RestTemplate secureRestTemplate;
    
    public TLSProxyController() throws Exception {
        this.secureRestTemplate = createHSMRestTemplate();
    }
    
    private RestTemplate createHSMRestTemplate() throws Exception {
        // Configurar PKCS#11 Provider
        String configPath = "classpath:hsm-config.cfg";
        Provider hsmProvider = new sun.security.pkcs11.SunPKCS11(configPath);
        Security.addProvider(hsmProvider);
        
        // Cargar KeyStore del HSM
        KeyStore keyStore = KeyStore.getInstance("PKCS11");
        keyStore.load(null, System.getenv("HSM_PIN").toCharArray());
        
        // Configurar SSLContext
        SSLContext sslContext = SSLContextBuilder.create()
            .loadKeyMaterial(keyStore, 
                System.getenv("HSM_PIN").toCharArray(),
                (aliases, socket) -> "cert-alias") // Alias del certificado en HSM
            .loadTrustMaterial(null, new TrustSelfSignedStrategy())
            .build();
        
        // Crear HttpClient con el SSLContext
        HttpClient httpClient = HttpClients.custom()
            .setSSLContext(sslContext)
            .setSSLHostnameVerifier(NoopHostnameVerifier.INSTANCE)
            .build();
        
        HttpComponentsClientHttpRequestFactory factory = 
            new HttpComponentsClientHttpRequestFactory(httpClient);
        
        return new RestTemplate(factory);
    }
    
    @RequestMapping(value = "/**", method = {RequestMethod.GET, RequestMethod.POST})
    public ResponseEntity<?> proxyRequest(
            HttpServletRequest request,
            @RequestHeader("X-Target-Host") String targetHost,
            @RequestBody(required = false) String body) {
        
        String targetUrl = buildTargetUrl(targetHost, request);
        HttpHeaders headers = extractHeaders(request);
        
        HttpEntity<String> entity = new HttpEntity<>(body, headers);
        
        return secureRestTemplate.exchange(
            targetUrl,
            HttpMethod.valueOf(request.getMethod()),
            entity,
            String.class
        );
    }
    
    private String buildTargetUrl(String targetHost, HttpServletRequest request) {
        return "https://" + targetHost + request.getRequestURI();
    }
}
```


### Solución 3: Integración con Service Mesh (Istio/Envoy) + HSM

Para entornos Kubernetes, la solución más productizada es usar un service mesh con soporte HSM:[^1_4][^1_5][^1_6]

**Arquitectura:**

1. **Istio/Envoy Sidecar** intercepta el tráfico
2. **HSM Private Key Provider** (extensión PKCS\#11)
3. Certificados gestionados por **cert-manager** o **SPIFFE/SPIRE**

**Ventajas:**

- Gestión automática de certificados[^1_7]
- mTLS transparente entre servicios[^1_8][^1_6]
- Integración nativa con HSM vía PKCS\#11[^1_9][^1_4]
- Observabilidad y políticas centralizadas

**Configuración Istio con HSM:**

```yaml
apiVersion: security.istio.io/v1beta1
kind: PeerAuthentication
metadata:
  name: default
spec:
  mtls:
    mode: STRICT

---
apiVersion: v1
kind: ConfigMap
metadata:
  name: hsm-config
data:
  hsm-pkcs11.cfg: |
    name = HSM-Module
    library = /usr/lib/libpkcs11.so
    slot = 0
```


### Solución 4: Proxy Comercial con Soporte HSM

Para entornos empresariales, considera soluciones comerciales:[^1_10][^1_11][^1_12]

1. **HAProxy Enterprise** con PKCS\#11[^1_10]
2. **NGINX Plus** con Cloud HSM[^1_12]
3. **Kong Enterprise** con mTLS + HSM[^1_13]
4. **F5 / Kemp LoadMaster**[^1_14]

**Ejemplo HAProxy con HSM:**

```haproxy
global
    ssl-engine pkcs11
    ssl-mode-async
    
frontend https-front
    bind *:443 ssl crt engine:pkcs11:pkcs11:object=my-cert
    default_backend secure-backend
    
backend secure-backend
    server external-service external.example.com:443 ssl verify required
```


### Solución 5: AWS CloudHSM + API Gateway

Si usas AWS, la integración nativa es muy robusta:[^1_15][^1_16]

```yaml
# NGINX con AWS CloudHSM
ssl_engine pkcs11;
ssl_certificate /etc/ssl/nginx/certificate.pem;
ssl_certificate_key "engine:pkcs11:pkcs11:object=nginx-key";
```

Esto se combina con API Gateway Lambda Authorizer para extraer y propagar identidad del certificado.[^1_17]

## Recomendaciones de Implementación

### 1. **Gestión de Secretos**

```java
@Value("${hsm.pin}")
private String hsmPin;

// O mejor, usar secrets manager
String hsmPin = System.getenv("HSM_PIN");
```


### 2. **Configuración de Logging**

```yaml
logging:
  level:
    sun.security.pkcs11: DEBUG
    org.springframework.cloud.gateway: DEBUG
```


### 3. **Health Check del HSM**

```java
@Component
public class HSMHealthIndicator implements HealthIndicator {
    
    @Override
    public Health health() {
        try {
            KeyStore ks = KeyStore.getInstance("PKCS11");
            ks.load(null, hsmPin.toCharArray());
            return Health.up()
                .withDetail("hsm", "connected")
                .build();
        } catch (Exception e) {
            return Health.down()
                .withDetail("error", e.getMessage())
                .build();
        }
    }
}
```


### 4. **Rotación de Certificados**

Usa **cert-manager** en Kubernetes o implementa un scheduler:[^1_7]

```java
@Scheduled(cron = "0 0 * * * *") // Cada hora
public void checkCertificateExpiration() {
    // Verificar expiración y renovar si es necesario
}
```


## Comparativa de Soluciones

| Solución | Complejidad | Escalabilidad | Coste | Recomendado para |
| :-- | :-- | :-- | :-- | :-- |
| Spring Cloud Gateway + PKCS\#11 | Media | Alta | Bajo | Microservicios Spring Boot[^1_18][^1_19] |
| RestTemplate personalizado | Baja | Media | Bajo | Aplicaciones simples[^1_1][^1_2] |
| Istio/Envoy + HSM | Alta | Muy Alta | Medio | Kubernetes/Service Mesh[^1_4][^1_6] |
| HAProxy/NGINX + HSM | Media | Muy Alta | Bajo | Proxies dedicados[^1_10][^1_12] |
| Soluciones comerciales | Baja | Muy Alta | Alto | Empresas con compliance estricto[^1_20] |

## Mejores Prácticas

1. **Usar certificados de corta duración** (días/horas) con rotación automática[^1_7]
2. **Implementar circuit breakers** para fallos del HSM[^1_21]
3. **Monitorizar expiración de certificados**[^1_11][^1_7]
4. **Usar mTLS en toda la cadena** cuando sea posible[^1_22][^1_23][^1_24]
5. **Centralizar gestión de certificados** con Vault o cert-manager[^1_7]
6. **Habilitar OCSP stapling** para validación de certificados[^1_10]
7. **Logging detallado de operaciones HSM** para auditoría[^1_25][^1_9]

## Conclusión

Para un entorno productivo Spring Boot, recomiendo:

- **Desarrollo/Testing**: RestTemplate con PKCS\#11 personalizado (Solución 2)
- **Producción (sin Kubernetes)**: Spring Cloud Gateway + PKCS\#11 (Solución 1) o HAProxy[^1_26][^1_10]
- **Producción (Kubernetes)**: Istio/Envoy con HSM Private Key Provider (Solución 3)[^1_6][^1_4][^1_7]
- **Enterprise**: Kong/HAProxy Enterprise con soporte HSM nativo (Solución 4)

La clave está en externalizar la complejidad del TLS offloading a un componente dedicado (gateway/proxy) que maneje la integración con el HSM vía PKCS\#11, mientras tus microservices se enfocan en la lógica de negocio.[^1_26][^1_9][^1_17][^1_11]
<span style="display:none">[^1_100][^1_101][^1_102][^1_103][^1_104][^1_105][^1_106][^1_107][^1_108][^1_109][^1_110][^1_111][^1_112][^1_113][^1_114][^1_115][^1_116][^1_117][^1_118][^1_119][^1_120][^1_121][^1_122][^1_123][^1_124][^1_125][^1_126][^1_127][^1_128][^1_129][^1_130][^1_131][^1_132][^1_133][^1_134][^1_135][^1_136][^1_137][^1_138][^1_139][^1_140][^1_141][^1_27][^1_28][^1_29][^1_30][^1_31][^1_32][^1_33][^1_34][^1_35][^1_36][^1_37][^1_38][^1_39][^1_40][^1_41][^1_42][^1_43][^1_44][^1_45][^1_46][^1_47][^1_48][^1_49][^1_50][^1_51][^1_52][^1_53][^1_54][^1_55][^1_56][^1_57][^1_58][^1_59][^1_60][^1_61][^1_62][^1_63][^1_64][^1_65][^1_66][^1_67][^1_68][^1_69][^1_70][^1_71][^1_72][^1_73][^1_74][^1_75][^1_76][^1_77][^1_78][^1_79][^1_80][^1_81][^1_82][^1_83][^1_84][^1_85][^1_86][^1_87][^1_88][^1_89][^1_90][^1_91][^1_92][^1_93][^1_94][^1_95][^1_96][^1_97][^1_98][^1_99]</span>
