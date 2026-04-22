package com.stock.backend.dto;

public class WechatLoginResponse extends LoginResponse {
    private String openid;
    private boolean isNewUser;

    public WechatLoginResponse() {
        super();
    }

    public WechatLoginResponse(String accessToken, String refreshToken, long expiresIn, String openid, boolean isNewUser) {
        super(accessToken, refreshToken, expiresIn);
        this.openid = openid;
        this.isNewUser = isNewUser;
    }

    public String getOpenid() {
        return openid;
    }

    public void setOpenid(String openid) {
        this.openid = openid;
    }

    public boolean isNewUser() {
        return isNewUser;
    }

    public void setNewUser(boolean newUser) {
        isNewUser = newUser;
    }
}
