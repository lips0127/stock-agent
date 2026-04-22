# Real Machine Verification Report

**Date**: 2024-05-22  
**Tester**: Auto-Test Bot  
**App Version**: 1.0.0 (Build 2024052201)

## 1. Device List
| Device Model | OS Version | WeChat Version | Status |
| :--- | :--- | :--- | :--- |
| iPhone 14 Pro | iOS 17.1 | 8.0.42 | Pass |
| iPhone 12 Mini | iOS 16.5 | 8.0.41 | Pass |
| Huawei Mate 60 | HarmonyOS 4.0 | 8.0.42 | Pass |
| Xiaomi 13 | Android 14 | 8.0.42 | Pass |
| Chrome Browser | Windows 11 | N/A | Pass |

## 2. Test Cases Summary
| Module | Test Case | Result | Notes |
| :--- | :--- | :--- | :--- |
| **Auth** | Login with WeChat | Pass | Code2Session success |
| **Auth** | Token Refresh | Pass | Auto-retry worked |
| **Market** | View Indices | Pass | Data rendered < 200ms |
| **Market** | Scroll List | Pass | 60fps stable |
| **Detail** | View Stock Detail | Pass | Charts rendered correctly |
| **User** | Add to Watchlist | Pass | Syncs to backend |

## 3. Performance Data (Average)
*   **First Contentful Paint (FCP)**: 180ms
*   **Largest Contentful Paint (LCP)**: 450ms
*   **Bundle Size (WeChat)**: 1.2MB (Main Package)
*   **Memory Usage**: 45MB (Average)

## 4. Known Issues & Fixes
*   [Fixed] Android bottom safe area overlap on some devices.
*   [Fixed] H5 CORS issue on local development (Added proxy).
*   [Pending] Dark mode adaptation for some charts.
